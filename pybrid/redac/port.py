import logging
import socket
logger = logging.getLogger(__name__)


def get_free_udp_port(start_port=5733, max_port=65535):
    """Find a free UDP port starting from the specified port."""
    for port in range(start_port, max_port + 1):
        try:
            # Create a UDP socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # Try to bind to the port
            sock.bind(('', port))
            # If successful, we found a free port
            sock.close()
            return port
        except OSError:
            # Port is in use, try the next one
            continue

    # No free port found in the range
    raise RuntimeError(f"No free UDP port found between {start_port} and {max_port}")