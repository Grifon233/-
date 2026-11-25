"""Put a predictable upper bound on request bodies before JSON parsing."""
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class RequestSizeLimit:
    _limits = {"/ingest": 128 * 1024, "/feedback": 32 * 1024}

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        prefix = scope.get("root_path", "").rstrip("/")
        if prefix and path.startswith(prefix + "/"):
            path = path[len(prefix):]
        if (limit := self._limits.get(path.rstrip("/"))) is None:
            await self.app(scope, receive, send)
            return

        async def too_large() -> None:
            await JSONResponse({"detail": "request_too_large"}, status_code=413)(scope, receive, send)

        for name, value in scope["headers"]:
            if name == b"content-length":
                try:
                    size = int(value)
                except ValueError:
                    await JSONResponse({"detail": "invalid_content_length"}, status_code=400)(
                        scope, receive, send,
                    )
                    return
                if size > limit:
                    await too_large()
                    return

        body = bytearray()
        while True:
            event = await receive()
            if event["type"] == "http.disconnect":
                return
            part = event.get("body", b"")
            if len(body) + len(part) > limit:
                await too_large()
                return
            body.extend(part)
            if not event.get("more_body"):
                break

        replayed = False

        async def replay():
            nonlocal replayed
            if replayed:
                return await receive()
            replayed = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay, send)
