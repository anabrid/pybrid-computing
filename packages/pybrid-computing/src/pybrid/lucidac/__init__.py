"""
The simple, stupid LUCIDAC python client classes.

Provides:
* LUCIDAC analog configuration and run management
* An easy HybridController class
* Basic typing
"""


__all__ = ["LUCIDAC", "Circuit"]


def __getattr__(name):
    """Lazy import to avoid circular dependency with pybrid.lucipy."""
    if name == "LUCIDAC":
        from pybrid.lucipy.computer import LucipyWrapper
        globals()["LUCIDAC"] = LucipyWrapper
        return LucipyWrapper
    if name == "Circuit":
        from pybrid.lucipy.circuits import Circuit
        globals()["Circuit"] = Circuit
        return Circuit
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
