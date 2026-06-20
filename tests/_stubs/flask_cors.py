"""Minimal flask_cors stub."""


def CORS(app=None, *a, **k):
    if app is not None:
        app.cors_config = k
    return None
