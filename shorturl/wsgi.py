"""WSGI entry point for hosts that do not run ASGI servers."""

from a2wsgi import ASGIMiddleware

from shorturl.api import app


application = ASGIMiddleware(app)
