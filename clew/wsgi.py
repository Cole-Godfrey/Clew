"""WSGI entry point for hosts that do not run ASGI servers."""

from threading import Lock

from a2wsgi import ASGIMiddleware


_adapter = None
_adapter_lock = Lock()


def application(environ, start_response):
    """Start the ASGI event loop in the worker, after a prefork server forks."""
    global _adapter
    if _adapter is None:
        with _adapter_lock:
            if _adapter is None:
                from clew.api import app

                _adapter = ASGIMiddleware(app)
    return _adapter(environ, start_response)
