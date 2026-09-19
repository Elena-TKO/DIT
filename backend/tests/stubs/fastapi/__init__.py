"""Минимальная заглушка FastAPI — ТОЛЬКО для проверки связки роутов там, где FastAPI не установлен."""
import io


class _Marker:
    def __init__(self, kind, default=None, dependency=None):
        self.kind, self.default, self.dependency = kind, default, dependency


def Depends(dep):
    return _Marker("depends", dependency=dep)


def Query(default=None, **_):
    return _Marker("query", default)


def Header(default=None, **_):
    return _Marker("header", default)


def Form(default=None, **_):
    return _Marker("form", default)


def File(default=None, **_):
    return _Marker("file", default)


class Request:
    def __init__(self, app=None):
        self.app = app


class UploadFile:
    def __init__(self, filename, data: bytes):
        self.filename = filename
        self.file = io.BytesIO(data)


class _Router:
    def __init__(self, prefix=""):
        self.prefix, self.routes = prefix, []

    def _add(self, method, path, **kw):
        def deco(fn):
            self.routes.append({"method": method, "path": self.prefix + path, "endpoint": fn, **kw})
            return fn
        return deco

    def get(self, path, **kw): return self._add("GET", path, **kw)
    def post(self, path, **kw): return self._add("POST", path, **kw)
    def put(self, path, **kw): return self._add("PUT", path, **kw)
    def patch(self, path, **kw): return self._add("PATCH", path, **kw)
    def delete(self, path, **kw): return self._add("DELETE", path, **kw)


class APIRouter(_Router):
    pass


class _State:
    pass


class FastAPI(_Router):
    def __init__(self, lifespan=None, **_):
        super().__init__()
        self.lifespan, self.state, self.handlers, self.middleware = lifespan, _State(), {}, []

    def add_middleware(self, cls, **kw):
        self.middleware.append((cls, kw))

    def exception_handler(self, exc):
        def deco(fn):
            self.handlers[exc] = fn
            return fn
        return deco

    def include_router(self, router):
        self.routes.extend(router.routes)

    def mount(self, *a, **kw):
        pass
