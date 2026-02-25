"""
Compatibility shim for the ``warnings.deprecated`` decorator.

Python 3.13 introduced ``warnings.deprecated``.  For older versions we
provide a thin wrapper that emits a ``DeprecationWarning`` on each call.
"""

try:
    from warnings import deprecated
except ImportError:
    import functools
    import warnings

    def deprecated(msg):
        """Emit a DeprecationWarning when the decorated function is called."""
        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                warnings.warn(msg, DeprecationWarning, stacklevel=2)
                return func(*args, **kwargs)
            return wrapper
        return decorator
