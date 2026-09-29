class Response:
    def __init__(self, content=None, status_code=200, media_type=None, headers=None):
        self.body, self.status_code, self.media_type, self.headers = content, status_code, media_type, headers or {}


class JSONResponse(Response):
    def __init__(self, status_code=200, content=None, **kw):
        super().__init__(content, status_code)


class HTMLResponse(Response):
    pass


class FileResponse(Response):
    def __init__(self, path, media_type=None, headers=None, **kw):
        super().__init__(None, 200, media_type, headers)
        self.path = path


class StreamingResponse(Response):
    def __init__(self, content=None, media_type=None, headers=None, **kw):
        super().__init__(content, 200, media_type, headers)


class PlainTextResponse(Response):
    def __init__(self, content=None, media_type=None, headers=None, **kw):
        super().__init__(content, 200, media_type, headers)
