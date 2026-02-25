#!/usr/bin/env python3
import subprocess
import json
import threading
import logging
import os
from threading import Thread, Lock
import pty
from time import sleep
import select


LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# === Logging setup ===
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(threadName)s] %(message)s",
    datefmt="%H:%M:%S"
)

mutex = Lock()


def monitor_board(board_name: str):
    """Run `tycmd monitor -b board_name` and log output."""
    logging.info(f"Starting monitor for board: {board_name}")

    # Create a pseudo-terminal
    master, slave = pty.openpty()

    try:
        process = subprocess.Popen(
            ["tycmd", "monitor", "--board", board_name],
            stdout=slave,
            stderr=slave,
            stdin=slave,
            text=True,
        )

        # Close the slave fd in the parent process
        os.close(slave)

        while True:
            # Check if data is available to read
            rlist, _, _ = select.select([master], [], [], 0.1)

            if rlist:
                try:
                    data = os.read(master, 1024).decode('utf-8', errors='replace')
                    if data:
                        for line in data.splitlines():
                            if line.strip():
                                logging.info(line)
                except OSError:
                    break

            # Check if process has exited
            if process.poll() is not None:
                break

        logging.info(f"Monitor for {board_name} wait for exit.")
        process.wait()
        logging.info(f"Monitor for {board_name} exited (code {process.returncode}).")

    finally:
        os.close(master)


def list_boards():
    """Return a list of connected board tags."""
    output = subprocess.check_output(["tycmd", "list", "--output", "json"], text=True)
    boards = json.loads(output)
    return [b["tag"] for b in boards]


def main():
    boards = list_boards()
    if not boards:
        logging.warning("No boards detected.")
        return

    logging.info(f"Found boards: {', '.join(boards)}")

    threads = []
    for board in boards:
        t = threading.Thread(target=monitor_board, args=(board,), name=board, daemon=True)
        t.start()
        threads.append(t)

    # Keep running until interrupted
    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        logging.info("Stopping monitors...")


if __name__ == "__main__":
    main()