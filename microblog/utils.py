from functools import wraps
import logging


def _trace(func):
    """Method call trace decorator."""

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        if func.__name__ != '__init__':
            logging.getLogger('trace').debug(
                'Calling: %s.%s, args=%r, kwargs=%r' % (
                    self.__class__.__name__,
                    func.__name__,
                    args, kwargs
                )
            )
        return func(self, *args, **kwargs)
    return wrapper


def trace_methods(cls):
    """Trace all method calls for given class."""

    for key, value in cls.__dict__.iteritems():
        if callable(value):
            setattr(cls, key, _trace(value))

