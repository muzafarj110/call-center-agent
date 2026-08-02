"""Minimal Flask stub for offline testing of daily_fresh.py."""


class _D(dict):
    def get(self, k, d=None):
        return super().get(k, d)


class _Req:
    def __init__(self):
        self.method = "GET"
        self._json = None
        self._args = {}
        self._form = {}
        self._headers = {}
        self._data = b""
        self.url = ""

    def set(self, method="GET", json=None, args=None, form=None, headers=None,
            data=b"", url=""):
        self.method = method
        self._json = json
        self._args = dict(args or {})
        self._form = dict(form or {})
        self._headers = dict(headers or {})
        self._data = data
        self.url = url
        return self

    @property
    def args(self):
        return _D(self._args)

    @property
    def form(self):
        return _D(self._form)

    @property
    def headers(self):
        return _D(self._headers)

    def get_json(self, silent=False, *a, **k):
        return self._json

    def get_data(self, *a, **k):
        return self._data


request = _Req()


class HTTPAbort(Exception):
    def __init__(self, code):
        super().__init__(f"abort({code})")
        self.code = code


def abort(code):
    raise HTTPAbort(code)


def jsonify(*a, **k):
    if a:
        return a[0]
    return dict(k)


class Response:
    def __init__(self, response="", status=200, mimetype=None, headers=None, **k):
        self.response = response
        self.status_code = status
        self.mimetype = mimetype
        self.headers = dict(headers or {})
        if mimetype:
            self.headers.setdefault("Content-Type", mimetype)

    def get_data(self, as_text=False):
        return self.response if as_text else self.response.encode()


class Flask:
    def __init__(self, name, *a, **k):
        self.name = name
        self.routes = {}

    def _reg(self, rule, methods):
        def deco(f):
            self.routes[(tuple(methods), rule)] = f
            return f
        return deco

    def route(self, rule, methods=None, **k):
        return self._reg(rule, methods or ["GET"])

    def get(self, rule, **k):
        return self._reg(rule, ["GET"])

    def post(self, rule, **k):
        return self._reg(rule, ["POST"])

    def run(self, *a, **k):
        pass
