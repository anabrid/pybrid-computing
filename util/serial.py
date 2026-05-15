#!/usr/bin/env python3
import json
import logging
import os
import pty
import select
import subprocess
import threading
from threading import Event, Lock, Thread
from time import sleep

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(threadName)s] %(message)s", datefmt="%H:%M:%S")

mutex = Lock()

# Maps board_tag -> {"thread": Thread, "stop_event": Event, "process": Popen}
active_monitors: dict = {}


def monitor_board(board_name: str, stop_event: Event):
    """Run `tycmd monitor -b board_name` and log output until stop_event is set."""
    logging.info(f"Starting monitor for board: {board_name}")

    master, slave = pty.openpty()

    try:
        process = subprocess.Popen(
            ["tycmd", "monitor", "--board", board_name],
            stdout=slave,
            stderr=slave,
            stdin=slave,
        )

        os.close(slave)

        # Store the process so the hotplug watcher can kill it
        with mutex:
            if board_name in active_monitors:
                active_monitors[board_name]["process"] = process

        while not stop_event.is_set():
            rlist, _, _ = select.select([master], [], [], 0.1)

            if rlist:
                try:
                    data = os.read(master, 1024).decode("utf-8", errors="replace")
                    if data:
                        for line in data.splitlines():
                            if line.strip():
                                logging.info(f"[{board_name}] {line}")
                except OSError:
                    break

            if process.poll() is not None:
                break

        # Terminate process if still running (board removed or stop requested)
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()

        logging.info(f"Monitor for {board_name} exited (code {process.returncode}).")

    finally:
        try:
            os.close(master)
        except OSError:
            pass


def list_boards() -> set:
    """Return a set of connected board tags."""
    try:
        output = subprocess.check_output(["tycmd", "list", "--output", "json"], text=True, stderr=subprocess.DEVNULL)
        boards = json.loads(output)
        return {b["tag"] for b in boards}
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return set()


def start_monitor(board: str):
    stop_event = Event()
    entry = {"stop_event": stop_event, "process": None}
    active_monitors[board] = entry

    t = Thread(
        target=monitor_board,
        args=(board, stop_event),
        name=f"monitor-{board}",
        daemon=True,
    )
    entry["thread"] = t
    t.start()
    logging.info(f"[hotplug] Board connected: {board}")


def stop_monitor(board: str):
    entry = active_monitors.pop(board, None)
    if not entry:
        return

    logging.info(f"[hotplug] Board disconnected: {board}")
    entry["stop_event"].set()

    # Directly kill the subprocess so the thread unblocks immediately
    proc = entry.get("process")
    if proc and proc.poll() is None:
        proc.terminate()

    thread = entry.get("thread")
    if thread:
        thread.join(timeout=5)


def hotplug_watcher(poll_interval: float = 1.0):
    """Continuously poll for board changes and manage monitor threads."""
    logging.info("Hotplug watcher started.")

    while True:
        current_boards = list_boards()

        with mutex:
            known_boards = set(active_monitors.keys())

        added = current_boards - known_boards
        removed = known_boards - current_boards

        with mutex:
            for board in added:
                start_monitor(board)

        for board in removed:
            with mutex:
                stop_monitor(board)

        sleep(poll_interval)


def main():
    # Start with currently connected boards
    initial_boards = list_boards()
    if not initial_boards:
        logging.warning("No boards detected at startup — waiting for connections...")
    else:
        logging.info(f"Found boards: {', '.join(initial_boards)}")
        with mutex:
            for board in initial_boards:
                start_monitor(board)

    watcher = Thread(target=hotplug_watcher, name="hotplug-watcher", daemon=True)
    watcher.start()

    try:
        watcher.join()
    except KeyboardInterrupt:
        logging.info("Shutting down...")
        with mutex:
            boards_to_stop = list(active_monitors.keys())
        for board in boards_to_stop:
            stop_monitor(board)
        logging.info("All monitors stopped.")


if __name__ == "__main__":
    main()
