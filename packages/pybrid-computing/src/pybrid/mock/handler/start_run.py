# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Handler for the start run command."""

import asyncio
import logging
from typing import TYPE_CHECKING, Union

import numpy as np

import pybrid.base.proto.main_pb2 as pb
from pybrid.mock.config import DummyDACErrorStage
from pybrid.mock.connection import ClientConnection
from pybrid.mock.handler.base import BaseHandler

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class StartRunHandler(BaseHandler):
    """
    Handler for start run commands.

    Executes run state machine, generates sample data, and sends
    state change notifications.
    """

    async def handle(
        self, cmd: pb.StartRunCommand, connection: ClientConnection
    ) -> Union[pb.StartRunResponse, pb.ErrorMessage]:
        """
        Execute run: send state changes and sample data.

        If error injection is configured at AT_START_RUN stage, returns an error
        immediately. Otherwise, starts an async task to execute the run in the
        background and returns a success response.

        :param cmd: The start run command with run configuration.
        :param connection: The client connection for sending notifications.
        :return: StartRunResponse on success or ErrorMessage if error injection is active.
        """
        run_id = cmd.run.id
        op_time_ns = self._parse_time(cmd.run_config.op_time)
        sample_rate = cmd.daq_config.sample_rate
        num_channels = cmd.daq_config.num_channels
        logger.debug(
            "START_RUN: run_id=%s, op_time=%dns, sample_rate=%dHz, channels=%d",
            run_id, op_time_ns, sample_rate, num_channels
        )

        if self.server.config.error_stage == DummyDACErrorStage.AT_START_RUN:
            logger.debug("START_RUN: Error injection active (AT_START_RUN)")
            return pb.ErrorMessage(
                description=self.server.config.error_message or "Start run error"
            )

        logger.debug("START_RUN: Launching async run execution task")
        task = asyncio.create_task(self._execute_run(cmd, connection))
        task.add_done_callback(lambda t: self._handle_task_result(t))
        return pb.StartRunResponse()

    def _handle_task_result(self, task: asyncio.Task) -> None:
        """Handle completion of run execution task, logging any exceptions."""
        if task.cancelled():
            return
        try:
            exc = task.exception()
            if exc is not None:
                logger.exception("Run execution task failed: %s", exc, exc_info=exc)
        except asyncio.InvalidStateError:
            pass  # Task not done yet (shouldn't happen in done callback)

    def _parse_time(self, time: pb.Time) -> int:
        """
        Convert pb.Time to nanoseconds.

        :param time: The protobuf Time message.
        :return: Time value in nanoseconds.
        """
        if time.prefix == pb.Prefix.NANO:
            return time.value
        elif time.prefix == pb.Prefix.MICRO:
            return time.value * 1_000
        elif time.prefix == pb.Prefix.MILLI:
            return time.value * 1_000_000
        else:  # pb.Prefix.NONE = seconds
            return time.value * 1_000_000_000

    def _get_adc_channel_count_from_config(self) -> int:
        """
        Get the number of ADC channels from the stored ConfigCommand.

        Counts ADC channels configured across all carriers in the stored
        module. This is more reliable than the DaqConfig
        in the StartRunCommand.

        :return: Total number of configured ADC channels, or 0 if no config stored.
        """
        if self.server._stored_config is None:
            logger.warning("No stored config - cannot determine ADC channel count")
            return 0

        total_channels = 0
        for config in self.server._stored_config.items:
            # Check if this config has an adc_config set
            if config.HasField("adc_config"):
                total_channels += len(config.adc_config.channels)

        logger.debug("ADC channel count from stored config: %d", total_channels)
        return total_channels

    async def _execute_run(self, cmd: pb.StartRunCommand, connection: ClientConnection):
        """
        Execute run state machine and generate samples.

        Sends state change notifications as the run progresses through its
        lifecycle (TAKE_OFF -> IC -> OP -> OP_END -> DONE), and generates
        sample data for each carrier.

        :param cmd: The start run command with run and daq configuration.
        :param connection: The client connection for sending messages.
        """
        run_id = cmd.run.id

        op_time_ns = self._parse_time(cmd.run_config.op_time)
        sample_rate = cmd.daq_config.sample_rate
        num_samples = max(1, int(op_time_ns * sample_rate / 1e9))
        # Prefer channel count from stored ConfigCommand; fall back to DaqConfig
        num_channels = self._get_adc_channel_count_from_config()
        if num_channels == 0 and cmd.daq_config.num_channels > 0:
            num_channels = cmd.daq_config.num_channels
            logger.debug(
                "START_RUN: Falling back to DaqConfig.num_channels=%d",
                num_channels,
            )

        logger.debug(
            "RUN[%s]: Starting execution - %d samples @ %dHz for %d channels (from config)",
            run_id[:8], num_samples, sample_rate, num_channels
        )

        zero_time = pb.Time(value=0, prefix=pb.Prefix.NONE)

        # Send state changes as notifications (id=None)
        if self.server.config.error_stage != DummyDACErrorStage.DROP_TAKEOFF_STATE:
            logger.debug("RUN[%s]: State -> TAKE_OFF", run_id[:8])
            msg = ClientConnection.new_message(
                pb.RunStateChangeMessage(
                    run=pb.Run(id=run_id, chunk=0),
                    time=zero_time,
                    old=pb.RunState.NEW,
                    new_=pb.RunState.TAKE_OFF
                ),
                id=None
            )
            await connection.send_message(msg)
        else:
            logger.debug("RUN[%s]: Skipping TAKE_OFF (DROP_TAKEOFF_STATE)", run_id[:8])

        logger.debug("RUN[%s]: State -> IC", run_id[:8])
        msg = ClientConnection.new_message(
            pb.RunStateChangeMessage(
                run=pb.Run(id=run_id, chunk=0),
                time=zero_time,
                old=pb.RunState.TAKE_OFF,
                new_=pb.RunState.IC
            ),
            id=None
        )
        await connection.send_message(msg)

        logger.debug("RUN[%s]: State -> OP", run_id[:8])
        msg = ClientConnection.new_message(
            pb.RunStateChangeMessage(
                run=pb.Run(id=run_id, chunk=0),
                time=zero_time,
                old=pb.RunState.IC,
                new_=pb.RunState.OP
            ),
            id=None
        )
        await connection.send_message(msg)

        # Optionally simulate real analogue computation time.
        # When simulate_op_time=True, samples are spread across the OP
        # duration with inter-chunk delays so that concurrent drain can
        # pick them up incrementally (instead of all arriving in a burst
        # after the full sleep).
        inter_chunk_delay: float = 0.0
        if self.server.config.simulate_op_time:
            op_time_seconds = op_time_ns / 1e9
            # Estimate total chunks across all carriers to distribute the
            # OP time evenly.  Each carrier produces
            #   ceil(actual_samples / chunk_size) chunks.
            chunk_size = 100
            actual_samples = num_samples
            if self.server.config.error_stage == DummyDACErrorStage.FEWER_SAMPLES:
                actual_samples = num_samples // 2
            chunks_per_carrier = max(1, (actual_samples + chunk_size - 1) // chunk_size)
            total_chunks = chunks_per_carrier * len(self.server._carrier_macs)
            inter_chunk_delay = op_time_seconds / max(1, total_chunks)
            logger.debug(
                "RUN[%s]: Simulating OP time (%.3f s) spread over %d chunks "
                "(%.4f s per chunk)",
                run_id[:8], op_time_seconds, total_chunks, inter_chunk_delay,
            )

        # Generate and send samples for each carrier
        logger.debug(
            "RUN[%s]: Generating samples for %d carriers",
            run_id[:8],
            len(self.server._carrier_macs)
        )
        for carrier_mac in self.server._carrier_macs:
            await self._send_carrier_samples(
                connection, run_id, carrier_mac, num_channels, num_samples,
                sample_rate, inter_chunk_delay=inter_chunk_delay,
            )

        # Check for DURING_RUN error
        if self.server.config.error_stage == DummyDACErrorStage.DURING_RUN:
            logger.debug("RUN[%s]: State -> ERROR (DURING_RUN error injection)", run_id[:8])
            msg = ClientConnection.new_message(
                pb.RunStateChangeMessage(
                    run=pb.Run(id=run_id, chunk=0),
                    time=zero_time,
                    old=pb.RunState.OP,
                    new_=pb.RunState.ERROR
                ),
                id=None
            )
            await connection.send_message(msg)
            return

        logger.debug("RUN[%s]: State -> OP_END", run_id[:8])
        msg = ClientConnection.new_message(
            pb.RunStateChangeMessage(
                run=pb.Run(id=run_id, chunk=0),
                time=zero_time,
                old=pb.RunState.OP,
                new_=pb.RunState.OP_END
            ),
            id=None
        )
        await connection.send_message(msg)

        # Send run data end for each carrier with final values
        logger.debug(
            "RUN[%s]: Sending RunDataEndMessage for %d carriers (%d channels)",
            run_id[:8],
            len(self.server._carrier_macs),
            num_channels
        )
        for carrier_mac in self.server._carrier_macs:
            final_values = self._generate_final_values(num_channels)
            final_data = pb.DaqData(
                data=final_values.astype(np.float32).tobytes(),
                type=pb.DataType(float_=pb.FloatType(bitwidth=32)),
                sample_count=1,
                channel_count=num_channels,
                channels=[pb.AdcChannel(idx=i, gain=1.0, offset=0.0, probe=i) for i in range(num_channels)]
            )
            msg = ClientConnection.new_message(
                pb.RunDataEndMessage(
                    run=pb.Run(id=run_id, chunk=0),
                    entity=pb.EntityId(path=f"/{carrier_mac}"),
                    data=final_data
                ),
                id=None
            )
            await connection.send_message(msg)

        if self.server.config.error_stage != DummyDACErrorStage.DROP_DONE_STATE:
            logger.debug("RUN[%s]: State -> DONE", run_id[:8])
            msg = ClientConnection.new_message(
                pb.RunStateChangeMessage(
                    run=pb.Run(id=run_id, chunk=0),
                    time=zero_time,
                    old=pb.RunState.OP_END,
                    new_=pb.RunState.DONE
                ),
                id=None
            )
            await connection.send_message(msg)
        else:
            logger.debug("RUN[%s]: Skipping DONE (DROP_DONE_STATE)", run_id[:8])

        logger.debug("RUN[%s]: Execution complete", run_id[:8])

    #: Amplitude scaling applied to samples/final-values when calibrated.
    CALIBRATION_SCALE = 0.5

    def _generate_samples(
        self, num_channels: int, num_samples: int, sample_rate: int
    ) -> np.ndarray:
        """
        Generate sine wave samples for each channel.

        Creates deterministic test data where each channel has a phase-shifted
        sine wave, making it easy to verify channel ordering and data integrity.

        When the server has been calibrated (``server._calibrated``), all
        sample amplitudes are scaled by :data:`CALIBRATION_SCALE`.

        :param num_channels: Number of channels to generate.
        :param num_samples: Number of samples per channel.
        :param sample_rate: Sample rate in Hz (used for time calculation).
        :return: Array of shape (num_channels, num_samples) with float32 values.
        """
        samples = np.zeros((num_channels, num_samples), dtype=np.float32)
        for i in range(num_channels):
            t = np.arange(num_samples) / sample_rate
            phase = i / 8 * 2 * np.pi
            samples[i] = np.sin(t + phase)
        if self.server._calibrated:
            samples *= self.CALIBRATION_SCALE
        return samples

    def _generate_final_values(self, num_channels: int) -> np.ndarray:
        """
        Generate final values for ADC channels.

        Creates deterministic test data representing the final sampled values
        at the end of a run (OP_END state).

        When the server has been calibrated (``server._calibrated``), all
        values are scaled by :data:`CALIBRATION_SCALE`.

        :param num_channels: Number of ADC channels from the client's DAQ config.
        :return: Array of shape (num_channels,) with float32 values.
        """
        final_values = np.zeros(num_channels, dtype=np.float32)
        half = num_channels // 2
        for i in range(num_channels):
            final_values[i] = (i - half) / max(half, 1)
        if self.server._calibrated:
            final_values *= self.CALIBRATION_SCALE
        return final_values

    async def _send_carrier_samples(
        self,
        connection: ClientConnection,
        run_id: str,
        carrier_mac: str,
        num_channels: int,
        num_samples: int,
        sample_rate: int,
        inter_chunk_delay: float = 0.0,
    ):
        """
        Send sample data for a carrier, chunked into messages.

        Generates sine wave samples and sends them in chunks of up to 100 samples.
        If FEWER_SAMPLES error injection is active, sends only half the expected
        samples.

        When *inter_chunk_delay* > 0, an ``asyncio.sleep`` is inserted between
        successive chunks so that samples are spread over the simulated OP time
        rather than arriving in a single burst.

        :param connection: The client connection for sending messages.
        :param run_id: The run identifier.
        :param carrier_mac: The carrier MAC address.
        :param num_channels: Number of channels.
        :param num_samples: Number of samples to generate.
        :param sample_rate: Sample rate in Hz.
        :param inter_chunk_delay: Seconds to sleep between chunk sends (0 = no delay).
        """
        logger.debug(
            "RUN[%s]: Generating %d samples for carrier %s (%d channels)",
            run_id[:8], num_samples, carrier_mac, num_channels
        )
        samples = self._generate_samples(num_channels, num_samples, sample_rate)

        # Handle FEWER_SAMPLES error injection
        actual_samples = num_samples
        if self.server.config.error_stage == DummyDACErrorStage.FEWER_SAMPLES:
            actual_samples = num_samples // 2
            samples = samples[:, :actual_samples]
            logger.debug(
                "RUN[%s]: FEWER_SAMPLES active - sending %d samples instead of %d",
                run_id[:8], actual_samples, num_samples
            )

        chunk_size = 100
        chunk = 0
        total_chunks = (actual_samples + chunk_size - 1) // chunk_size

        for start in range(0, actual_samples, chunk_size):
            end = min(start + chunk_size, actual_samples)
            chunk_samples = samples[:, start:end]

            daq_data = pb.DaqData(
                data=chunk_samples.astype(np.float32).flatten(order='F').tobytes(),
                type=pb.DataType(float_=pb.FloatType(bitwidth=32)),
                sample_count=end - start,
                channel_count=num_channels,
                channels=[pb.AdcChannel(idx=i, gain=1.0, offset=0.0, probe=i) for i in range(num_channels)]
            )

            msg = pb.RunDataMessage(
                run=pb.Run(id=run_id, chunk=chunk),
                entity=pb.EntityId(path=f"/{carrier_mac}"),
                data=daq_data
            )

            await connection.send_message(ClientConnection.new_message(msg, id=None))
            logger.debug(
                "RUN[%s]: Sent chunk %d/%d (%d samples) for carrier %s",
                run_id[:8], chunk + 1, total_chunks, end - start, carrier_mac
            )
            chunk += 1

            # Spread chunks over the simulated OP time so concurrent drain
            # can pick them up incrementally.
            if inter_chunk_delay > 0:
                await asyncio.sleep(inter_chunk_delay)

        logger.debug(
            "RUN[%s]: Finished sending %d samples in %d chunks for carrier %s",
            run_id[:8], actual_samples, chunk, carrier_mac
        )
