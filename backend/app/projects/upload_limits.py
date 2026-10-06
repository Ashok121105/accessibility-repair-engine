from typing import Any

from starlette.responses import JSONResponse

from backend.app.projects.analyzer import MAX_REQUEST_BYTES

PROJECT_ANALYZE_PATH = "/api/project/analyze"


class RequestBodyTooLarge(Exception):
    pass


class UploadSizeLimitMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if (
            scope.get("type") != "http"
            or scope.get("method") != "POST"
            or scope.get("path") != PROJECT_ANALYZE_PATH
        ):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                declared_length = int(raw_length)
            except ValueError:
                response = JSONResponse(
                    {"detail": "Invalid upload Content-Length"},
                    status_code=400,
                )
                await response(scope, receive, send)
                return
            if declared_length > MAX_REQUEST_BYTES:
                response = JSONResponse(
                    {"detail": "The upload request exceeds the 14 MB limit"},
                    status_code=413,
                )
                await response(scope, receive, send)
                return

        received = 0

        async def bounded_receive() -> dict[str, Any]:
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_REQUEST_BYTES:
                    raise RequestBodyTooLarge
            return message

        try:
            await self.app(scope, bounded_receive, send)
        except RequestBodyTooLarge:
            response = JSONResponse(
                {"detail": "The upload request exceeds the 14 MB limit"},
                status_code=413,
            )
            await response(scope, receive, send)
