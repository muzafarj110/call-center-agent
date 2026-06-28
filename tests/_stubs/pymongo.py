"""Minimal in-memory MongoDB stub for offline testing."""

ASCENDING = 1
DESCENDING = -1


def _match(doc, q):
    for k, v in (q or {}).items():
        if isinstance(v, dict) and "$exists" in v:
            if v["$exists"] != (k in doc):
                return False
        elif doc.get(k) != v:
            return False
    return True


class _Cursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, key=None, direction=1, *a, **k):
        try:
            if isinstance(key, str):
                self.docs.sort(key=lambda d: d.get(key), reverse=(direction == -1))
        except Exception:
            pass
        return self

    def limit(self, n):
        self.docs = self.docs[:n]
        return self

    def __iter__(self):
        return iter(self.docs)


class _Res:
    def __init__(self, matched=0, modified=0, upserted=None, inserted=None):
        self.matched_count = matched
        self.modified_count = modified
        self.upserted_id = upserted
        self.inserted_id = inserted


class _Coll:
    def __init__(self):
        self.docs = []
        self._id = 0

    def create_index(self, *a, **k):
        return "idx"

    def insert_one(self, doc):
        self._id += 1
        d = dict(doc)
        d.setdefault("_id", self._id)
        self.docs.append(d)
        return _Res(inserted=d["_id"])

    def insert_many(self, docs):
        ids = [self.insert_one(d).inserted_id for d in docs]
        return _Res(inserted=ids)

    def find(self, q=None, proj=None):
        out = []
        for d in self.docs:
            if _match(d, q):
                dd = dict(d)
                if proj and proj.get("_id") == 0:
                    dd.pop("_id", None)
                out.append(dd)
        return _Cursor(out)

    def find_one(self, q=None, proj=None):
        for d in self.docs:
            if _match(d, q):
                dd = dict(d)
                if proj and proj.get("_id") == 0:
                    dd.pop("_id", None)
                return dd
        return None

    def _apply(self, d, update):
        d.update(update.get("$set", {}))
        for k in (update.get("$unset", {}) or {}):
            d.pop(k, None)

    def update_one(self, q, update, upsert=False):
        for d in self.docs:
            if _match(d, q):
                self._apply(d, update)
                return _Res(matched=1, modified=1)
        if upsert:
            doc = dict(q)
            doc.update(update.get("$set", {}))
            r = self.insert_one(doc)
            return _Res(upserted=r.inserted_id)
        return _Res()

    def update_many(self, q, update):
        n = 0
        for d in self.docs:
            if _match(d, q):
                self._apply(d, update)
                n += 1
        return _Res(matched=n, modified=n)

    def delete_one(self, q):
        for i, d in enumerate(self.docs):
            if _match(d, q):
                self.docs.pop(i)
                return _Res(modified=1)
        return _Res()

    def delete_many(self, q):
        before = len(self.docs)
        self.docs = [d for d in self.docs if not _match(d, q)]
        return _Res(modified=before - len(self.docs))

    def count_documents(self, q=None):
        return len([d for d in self.docs if _match(d, q)])


class _DB:
    def __init__(self):
        object.__setattr__(self, "_colls", {})

    def _coll(self, name):
        c = self._colls.get(name)
        if c is None:
            c = _Coll()
            self._colls[name] = c
        return c

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._coll(name)

    def __getitem__(self, name):
        return self._coll(name)


class _Admin:
    def command(self, *a, **k):
        return {"ok": 1}


class MongoClient:
    _shared = None

    def __init__(self, *a, **k):
        if MongoClient._shared is None:
            MongoClient._shared = _DB()
        self.admin = _Admin()

    def __getitem__(self, name):
        return MongoClient._shared

    def get_default_database(self):
        return MongoClient._shared
