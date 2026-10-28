import asyncio

import pytest

from aletheia_nexus.cli import entrypoint
from aletheia_nexus.workbench.security import LoopbackGuard


@pytest.mark.parametrize("transport", ["http", "websocket"])
@pytest.mark.parametrize(
    "headers,allowed",
    [
        ({"host": "127.0.0.1:8080"}, True),
        ({"host": "localhost:8080", "origin": "http://localhost:8080"}, True),
        ({"host": "127.0.0.1:8080", "origin": "https://attacker.test"}, False),
        ({"host": "attacker.test:8080"}, False),
        ({"host": "127.0.0.1:8080", "sec-fetch-site": "cross-site"}, False),
        ({"host": "127.0.0.1:8080", "origin": "null"}, False),
    ],
)
def test_http_and_websocket_origin_boundary(headers, allowed, transport):
    called, messages = [], []

    async def inner(scope, receive, send):
        called.append(True)

    async def send(message):
        messages.append(message)

    guard = LoopbackGuard(inner, port=8080)
    asyncio.run(
        guard(
            {
                "type": transport,
                "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
            },
            None,
            send,
        )
    )
    assert bool(called) == allowed
    if not allowed:
        assert messages[0].get("status", messages[0].get("code")) in {403, 1008}


def test_ui_help_keeps_existing_cli_lazy(capsys):
    with pytest.raises(SystemExit) as exc:
        entrypoint(["ui", "--help"])
    assert exc.value.code == 0
    assert "127.0.0.1" in capsys.readouterr().out
