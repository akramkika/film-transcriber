"""Bound raw multipart bodies before disk spooling and restrict browser origins."""

from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class LocalUploadGuard:
    """Limit upload bytes even with chunked requests, without buffering the body."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes + 1024 * 1024  # bounded multipart field/header overhead

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        origin = headers.get("origin")
        if (
            scope["method"] in {"POST", "DELETE"}
            and origin
            and urlsplit(origin).netloc != headers.get("host")
        ):
            response = JSONResponse(
                {
                    "error": {
                        "category": "invalid_origin",
                        "message": "Cette action doit être lancée depuis l'application locale.",
                    }
                },
                403,
            )
            await response(scope, receive, send)
            return
        if scope["method"] != "POST":
            await self.app(scope, receive, send)
            return
        try:
            length = int(headers.get("content-length", "0"))
        except ValueError:
            length = self.max_bytes + 1
        if length < 0 or length > self.max_bytes:
            response = JSONResponse(
                {
                    "error": {
                        "category": "file_too_large",
                        "message": "La vidéo dépasse la taille autorisée.",
                    }
                },
                413,
            )
            await response(scope, receive, send)
            return
        total = 0

        async def limited_receive() -> Message:
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > self.max_bytes:
                    raise HTTPException(413, "La vidéo dépasse la taille autorisée.")
            return message

        await self.app(scope, limited_receive, send)
