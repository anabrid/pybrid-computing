from typing import Optional


class AddressingMap:
    """Linearized mapping schemes for generating deterministic MAC addresses in tests."""

    @staticmethod
    def map_lucistack(ix: int) -> Optional[str]:
        if ix < 256:
            return f"00-00-00-00-00-{ix:02x}"

        return None

    @staticmethod
    def index_of_redac(mac: str) -> Optional[int]:
        """Reverse lookup: return the linear index of a virtual REDAC address, or None."""
        for ix in range(12):
            if AddressingMap.map_redac(ix) == mac:
                return ix
        return None

    @staticmethod
    def map_redac(ix: int) -> Optional[str]:
        _VIRTUAL_ADDRESSES = [
            "00-00-00-00-00-00",
            "00-00-00-00-00-01",
            "00-00-00-00-00-02",
            "00-00-01-00-00-00",
            "00-00-01-00-00-01",
            "00-00-01-00-00-02",
            "01-00-00-00-00-00",
            "01-00-00-00-00-01",
            "01-00-00-00-00-02",
            "01-00-01-00-00-00",
            "01-00-01-00-00-01",
            "01-00-01-00-00-02",
        ]

        if ix < len(_VIRTUAL_ADDRESSES):
            return _VIRTUAL_ADDRESSES[ix]

        return None
