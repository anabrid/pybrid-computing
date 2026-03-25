"""MDR block test — three-phase verification of all operation modes.

Phase 1: Multiply, square, and identity path verification (single run).
Phase 2: Square-root grid search with accuracy scatter plot.
Phase 3: Division grid search with accuracy scatter plot.

Connects to a real REDAC, finds the first cluster containing an MMDRBlock,
and exercises each operation across a range of operand values.

Usage:
    uv run python examples/standalone/mdr/mdr.py
"""

import asyncio
import logging

import numpy as np
from matplotlib import pyplot as plt

from pybrid.base.utils.logging import set_pybrid_logging_level
from pybrid.base.analog.computations import (
    Multiplication, Square, Division, SquareRoot,
)
from pybrid.redac import DAQConfig, RunConfig
from pybrid.redac.blocks.mblock import MMDRBlock
from pybrid.redac.carrier import ADCChannel
from pybrid.lucidac import Controller as LUCIDACController
from pybrid.redac import Controller as REDACController

#logging.basicConfig()
#set_pybrid_logging_level(logging.DEBUG)

REDAC_HOST = "192.168.150.69"
REDAC_PORT = 5732

TOLERANCE = 5e-2
GRID = np.linspace(-1.0, 1.0, 21)
OP_TIME = 10_000_000
SAMPLE_RATE = 10_000


def find_first_mdr_cluster(computer):
    """Return the first (carrier, cluster, mdr_block) tuple with an MMDRBlock."""
    for carrier in computer.carriers:
        for cluster in carrier.clusters:
            if isinstance(cluster.m0block, MMDRBlock):
                return carrier, cluster, cluster.m0block
            if isinstance(cluster.m1block, MMDRBlock):
                return carrier, cluster, cluster.m1block
    raise RuntimeError("No cluster with an MMDRBlock found.")


def steady_state(channel_data):
    """Extract steady-state value as median of the last half of samples."""
    samples = np.array(channel_data).flatten()
    return np.median(samples[len(samples) // 2 :])


def prepare_cluster(cluster, mdr):
    """Reset Python model state and enable the constant generator."""
    cluster.ublock.reset()
    cluster.cblock.reset()
    cluster.iblock.reset()
    mdr.reset()
    cluster.ublock.set_constant(1.0)


def wire_element(cluster, m_offset, idx, x, y=None):
    """Route constant through CBlock/IBlock to MDR element *idx*.

    Sets CBlock coefficient lanes and IBlock routing for the x input
    (and optionally y) of the MDR element at position *idx*.
    """
    CONST = 15
    cluster.ublock.connect(CONST, idx, force=True)
    cluster.cblock.elements[idx].factor = x
    cluster.iblock.connect(idx, m_offset + 2 * idx, force=True)

    if y is not None:
        y_lane = 4 + idx
        cluster.ublock.connect(CONST, y_lane, force=True)
        cluster.cblock.elements[y_lane].factor = y
        cluster.iblock.connect(y_lane, m_offset + 2 * idx + 1, force=True)


async def run_batch(controller, computer, carrier, mdr, n_channels):
    """Clear DAQ state, capture *n_channels* MDR elements, and execute a run."""
    carrier.adc_config.clear()
    computer.daq.reset()

    for i in range(n_channels):
        computer.daq.capture(mdr.elements[i])

    session = controller.create_session()
    runs = await (
        session
        .set_config(computer)
        .run(
            RunConfig(op_time=OP_TIME),
            daq=DAQConfig(num_channels=n_channels, sample_rate=SAMPLE_RATE),
        )
        .execute()
    )
    return runs[0]


# -- Phase 1: Multiply, Square, Identity ------------------------------------

async def phase1(controller, computer, carrier, cluster, mdr, m_offset):
    """Verify multiply, square, and identity paths with fixed inputs."""
    print("\n=== Phase 1: Multiply, Square, Identity ===")

    prepare_cluster(cluster, mdr)

    W_X, W_Y = 0.5, 0.3

    mdr.elements[0].op = Multiplication()
    mdr.elements[1].op = Square()
    # Elements 2-3 left as default (Multiplication) for identity capture.
    for i in range(4):
        wire_element(cluster, m_offset, i, W_X, W_Y)

    # Capture computation outputs for elements 0 (mul) and 1 (square).
    carrier.adc_config.clear()
    computer.daq.reset()
    computer.daq.capture(mdr.elements[0], mdr.elements[1])

    # Capture the four hardwired identity outputs (y passthrough, lanes 4-7).
    cluster_idx = int(cluster.path.id_)
    m_slot = 0 if cluster.m0block is mdr else 1
    for ident in range(4):
        sig = cluster_idx * 16 + m_slot * 8 + 4 + ident
        probe = computer.daq._next_probe_index
        computer.daq._next_probe_index += 1
        carrier.adc_config.append(ADCChannel(index=sig, probe=probe))

    session = controller.create_session()
    runs = await (
        session
        .set_config(computer)
        .run(
            RunConfig(op_time=OP_TIME),
            daq=DAQConfig(num_channels=6, sample_rate=SAMPLE_RATE),
        )
        .execute()
    )
    run = runs[0]

    expected = [W_X * W_Y, W_X**2, -W_Y, -W_Y, -W_Y, -W_Y]
    labels = ["mul(x*y)", "sq(x^2)", "id y[0]", "id y[1]", "id y[2]", "id y[3]"]

    all_ok = True
    for i, (lbl, exp) in enumerate(zip(labels, expected)):
        val = steady_state(run.data[i])
        ok = abs(val - exp) < TOLERANCE
        all_ok &= ok
        print(f"  {lbl}: exp={exp:.4f}  meas={val:.4f}  [{'OK' if ok else 'FAIL'}]")
    return all_ok


# -- Phase 2: Square-root grid search ---------------------------------------

async def phase2(controller, computer, carrier, cluster, mdr, m_offset):
    """Grid search for sqrt(x), x in [0, 1].

    The MDR sqrt block expects the negated operand: to compute sqrt(x) we set
    the CBlock factor to x, the IBlock inverts it to -x, and the hardware
    evaluates sqrt(-(-x)) = sqrt(x).
    """
    print("\n=== Phase 2: sqrt(x) Grid Search ===")

    # (original_x, cblock_factor, expected_output)
    valid = [
        (x, -x, np.sqrt(x))
        for x in GRID
        if x >= 0 and np.sqrt(x) <= 1.0
    ]
    print(f"  {len(valid)} test points")

    results = []
    for start in range(0, len(valid), 4):
        batch = valid[start : start + 4]
        n = len(batch)

        prepare_cluster(cluster, mdr)
        for i, (_, cf, _) in enumerate(batch):
            mdr.elements[i].op = SquareRoot()
            wire_element(cluster, m_offset, i, cf)

        run = await run_batch(controller, computer, carrier, mdr, n)
        for i, (x_orig, _, exp) in enumerate(batch):
            val = steady_state(run.data[i])
            ok = abs(val - exp) < TOLERANCE
            print(f"  sqrt({x_orig:+.2f}): exp={exp:.4f}  meas={val:.4f}  [{'OK' if ok else 'FAIL'}]")
            results.append((x_orig, exp, val))

    return results


# -- Phase 3: Division grid search ------------------------------------------

async def phase3(controller, computer, carrier, cluster, mdr, m_offset):
    """Grid search for x/y, both operands in [-1, 1]."""
    print("\n=== Phase 3: x/y Division Grid Search ===")

    valid = [
        (x, y, x / y)
        for x in GRID
        for y in GRID
        if abs(y) > 1e-9 and abs(x / y) <= 1.0
    ]
    print(f"  {len(valid)} test points")

    results = []
    for start in range(0, len(valid), 4):
        batch = valid[start : start + 4]
        n = len(batch)

        prepare_cluster(cluster, mdr)
        for i, (x, y, _) in enumerate(batch):
            mdr.elements[i].op = Division()
            wire_element(cluster, m_offset, i, x, y)

        run = await run_batch(controller, computer, carrier, mdr, n)
        for i, (x, y, exp) in enumerate(batch):
            val = steady_state(run.data[i])
            ok = abs(val - exp) < TOLERANCE
            print(f"  {x:+.2f}/{y:+.2f}: exp={exp:.4f}  meas={val:.4f}  [{'OK' if ok else 'FAIL'}]")
            results.append((x, y, exp, val))

    return results


# -- Plotting ----------------------------------------------------------------

def plot_sqrt_accuracy(ax, results, title):
    """Scatter x operand on x-axis, fixed y=1; blue = pass, red = fail."""
    xs = np.array([r[0] for r in results])
    exp = np.array([r[1] for r in results])
    meas = np.array([r[2] for r in results])
    err = np.abs(meas - exp)
    ok = err < TOLERANCE
    ys = np.ones_like(xs)

    ax.scatter(
        xs[ok], ys[ok], c="blue", s=20, label=f"pass ({ok.sum()})", zorder=2
    )
    ax.scatter(
        xs[~ok], ys[~ok], c="red", s=20, label=f"fail ({(~ok).sum()})", zorder=2
    )
    ax.set_xlim(-1.1, 1.1)
    ax.set_xlabel("x")
    ax.set_title(title)
    ax.legend(fontsize="small")

    print(f"  {title}: {ok.sum()}/{len(results)} passed (tol={TOLERANCE})")


def plot_div_accuracy(ax, results, title):
    """Scatter x vs y operands; blue = pass, red = fail."""
    xs = np.array([r[0] for r in results])
    ys = np.array([r[1] for r in results])
    exp = np.array([r[2] for r in results])
    meas = np.array([r[3] for r in results])
    err = np.abs(meas - exp)
    ok = err < TOLERANCE

    ax.scatter(
        xs[ok], ys[ok], c="blue", s=20, label=f"pass ({ok.sum()})", zorder=2
    )
    ax.scatter(
        xs[~ok], ys[~ok], c="red", s=20, label=f"fail ({(~ok).sum()})", zorder=2
    )
    ax.set_xlim(-1.1, 1.1)
    ax.set_ylim(-1.1, 1.1)
    ax.set_xlabel("x")
    ax.set_ylabel("y")
    ax.set_title(title)
    ax.legend(fontsize="small")
    ax.set_aspect("equal")

    print(f"  {title}: {ok.sum()}/{len(results)} passed (tol={TOLERANCE})")


# -- Main --------------------------------------------------------------------

async def main():
    # controller = LUCIDACController()
    controller = REDACController()
    await controller.add_device(REDAC_HOST, REDAC_PORT)

    async with controller:
        computer = controller.computer
        carrier, cluster, mdr = find_first_mdr_cluster(computer)
        m_offset = 0 if cluster.m0block is mdr else 8
        print(f"MDR block at {mdr.path}")

        await phase1(controller, computer, carrier, cluster, mdr, m_offset)
        sqrt_results = await phase2(
            controller, computer, carrier, cluster, mdr, m_offset
        )
        div_results = await phase3(
            controller, computer, carrier, cluster, mdr, m_offset
        )

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    plot_sqrt_accuracy(ax1, sqrt_results, "sqrt(x)")
    plot_div_accuracy(ax2, div_results, "x / y")
    fig.suptitle("MDR Block Accuracy")
    plt.tight_layout()
    plt.show()


asyncio.run(main())
