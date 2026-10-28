"""Same-origin loopback boundary for both HTTP and Socket.IO/WebSocket traffic."""

from urllib.parse import urlsplit


class LoopbackGuard:
    def __init__(self, app, *, port: int):
        self.app, self.port = app, port
        self.authorities = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if port == 80:
            self.authorities |= {"127.0.0.1", "localhost"}

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope.get("headers", [])
        }
        host = headers.get("host", "").lower()
        origin = headers.get("origin")
        valid_origin = True
        if origin:
            parsed = urlsplit(origin)
            valid_origin = (
                parsed.scheme == "http"
                and parsed.netloc.lower() == host
                and not parsed.path
                and not parsed.query
                and not parsed.fragment
            )
        denied = (
            host not in self.authorities
            or not valid_origin
            or headers.get("sec-fetch-site") == "cross-site"
        )
        if denied:
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                await send(
                    {
                        "type": "http.response.start",
                        "status": 403,
                        "headers": [(b"content-type", b"text/plain; charset=utf-8")],
                    }
                )
                await send(
                    {
                        "type": "http.response.body",
                        "body": b"Local workbench requires same-origin loopback access",
                    }
                )
            return

        async def secure_send(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"SAMEORIGIN"),
                        (b"content-security-policy", b"frame-ancestors 'self'"),
                    ]
                )
            await send(message)

        await self.app(scope, receive, secure_send)
