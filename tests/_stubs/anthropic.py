"""Minimal anthropic stub (not exercised; ai_reply/extract_record are patched)."""


class _Block:
    def __init__(self, text):
        self.text = text


class _Resp:
    def __init__(self, text):
        self.content = [_Block(text)]


class _Messages:
    def create(self, *a, **k):
        return _Resp("[stub] no live model in tests")


class Anthropic:
    def __init__(self, *a, **k):
        self.messages = _Messages()
