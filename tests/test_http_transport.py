"""`OUTLOOK_MCP_TRANSPORT=streamable-http`: opt-in, and closed by default (#126).

stdio is how every client launches this server today, so the first thing pinned
here is that its path did not move: `main` still makes exactly the call it made
before, and the HTTP variables are not even read unless HTTP was asked for.

The rest pins the security model. Loopback unless told otherwise; a bind other
machines can reach refuses to start without a bearer token; with a token, every
request carries it or gets 401 before it reaches the MCP layer; nothing logs the
token or a request URL. The round-trip tests run the production uvicorn config on
an ephemeral port, so they see what an HTTP client sees, not what a mock was told.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time

import httpx2
import pytest
import uvicorn
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client

from outlook_mcp import http_transport, server
from outlook_mcp.config import Config
from outlook_mcp.http_transport import (
    HOST_ENV,
    PORT_ENV,
    TOKEN_ENV,
    TRANSPORT_ENV,
    HttpSettings,
    settings_from_env,
)

# Synthetic, and shaped like real ones: 32+ characters of the RFC 6750 alphabet.
TOKEN = "test-token-" + "a" * 32
ROTATED = "rotated-token-" + "b" * 32
WRONG = "wrong-token-" + "c" * 32

HTTP = {TRANSPORT_ENV: "streamable-http"}

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}


# ── stdio stays the default ─────────────────────────────────────────────


@pytest.fixture
def no_transport_env(monkeypatch):
    for name in (TRANSPORT_ENV, HOST_ENV, PORT_ENV, TOKEN_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(server, "load_config", lambda: Config())


@pytest.mark.parametrize(
    "env",
    [
        {},
        {TRANSPORT_ENV: ""},
        {TRANSPORT_ENV: "stdio"},
        # The HTTP settings are not read at all on stdio, so values that would
        # be refused on HTTP change nothing here.
        {HOST_ENV: "0.0.0.0", PORT_ENV: "not-a-port", TOKEN_ENV: "short"},
    ],
    ids=["unset", "empty", "stdio", "http-vars-without-transport"],
)
def test_stdio_stays_the_default(env, no_transport_env, monkeypatch):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    runs = []
    monkeypatch.setattr(server.mcp, "run", lambda *args, **kwargs: runs.append((args, kwargs)))
    monkeypatch.setattr(http_transport, "serve", lambda *_: pytest.fail("HTTP must not start"))

    server.main()

    # The exact call main made before HTTP existed.
    assert runs == [((), {"transport": "stdio"})]


def test_http_is_served_only_when_asked_for(no_transport_env, monkeypatch):
    monkeypatch.setenv(TRANSPORT_ENV, "streamable-http")
    served = []
    monkeypatch.setattr(server.mcp, "run", lambda *_, **__: pytest.fail("stdio must not start"))
    monkeypatch.setattr(http_transport, "serve", lambda mcp, settings: served.append(settings))

    server.main()

    assert served == [HttpSettings()]


# ── Refused before anything binds ───────────────────────────────────────


@pytest.mark.parametrize(
    "env, named",
    [
        ({TRANSPORT_ENV: "http"}, TRANSPORT_ENV),
        ({**HTTP, HOST_ENV: "0.0.0.0"}, TOKEN_ENV),
        ({**HTTP, PORT_ENV: "eighty"}, PORT_ENV),
        ({**HTTP, TOKEN_ENV: "short"}, TOKEN_ENV),
    ],
    ids=["unknown-transport", "public-bind-without-token", "bad-port", "bad-token"],
)
def test_main_exits_with_the_reason_and_starts_nothing(
    env, named, no_transport_env, monkeypatch, capsys
):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(server.mcp, "run", lambda *_, **__: pytest.fail("stdio must not start"))
    monkeypatch.setattr(http_transport, "serve", lambda *_: pytest.fail("HTTP must not start"))

    with pytest.raises(SystemExit) as exc:
        server.main()

    assert exc.value.code == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert named in err


def test_defaults_are_loopback_port_8000_and_no_token():
    assert settings_from_env(HTTP) == HttpSettings(host="127.0.0.1", port=8000, tokens=())


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.2", "localhost", "::1"])
def test_a_loopback_bind_needs_no_token(host):
    assert settings_from_env({**HTTP, HOST_ENV: host}).tokens == ()


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.0.2.10", "2001:db8::1", "mcp.example.com"])
def test_a_bind_other_machines_can_reach_needs_a_token(host):
    with pytest.raises(ValueError, match=TOKEN_ENV):
        settings_from_env({**HTTP, HOST_ENV: host})

    # ...and is accepted once one is set.
    assert settings_from_env({**HTTP, HOST_ENV: host, TOKEN_ENV: TOKEN}).host == host


def test_tokens_are_comma_separated_so_one_can_be_rotated():
    settings = settings_from_env({**HTTP, TOKEN_ENV: f" {TOKEN} ,{ROTATED},"})

    assert settings.tokens == (TOKEN, ROTATED)


@pytest.mark.parametrize(
    "bad",
    ["x" * 31, "has space " + "x" * 32, 'quote"' + "x" * 32, "ü" + "x" * 32],
    ids=["too-short", "space", "quote", "non-ascii"],
)
def test_an_unusable_token_is_refused_without_being_echoed(bad):
    with pytest.raises(ValueError, match=TOKEN_ENV) as exc:
        settings_from_env({**HTTP, TOKEN_ENV: f"{TOKEN},{bad}"})

    assert bad not in str(exc.value)
    assert TOKEN not in str(exc.value)


def test_the_settings_never_print_their_tokens():
    assert TOKEN not in repr(settings_from_env({**HTTP, TOKEN_ENV: TOKEN}))


@pytest.mark.parametrize("port", ["eighty", "0", "65536", "-1", "80.5"])
def test_an_invalid_port_is_refused(port):
    with pytest.raises(ValueError, match=PORT_ENV):
        settings_from_env({**HTTP, PORT_ENV: port})


def test_without_a_token_the_sdk_app_is_served_unwrapped():
    app = http_transport.build_app(server.mcp, HttpSettings())

    assert not isinstance(app, http_transport.BearerTokenMiddleware)


# ── A real HTTP round trip ──────────────────────────────────────────────


@pytest.fixture(scope="module")
def base_url():
    """The production uvicorn config, on an ephemeral loopback port."""
    settings = HttpSettings(host="127.0.0.1", port=0, tokens=(TOKEN, ROTATED))
    instance = uvicorn.Server(http_transport.uvicorn_config(server.mcp, settings))
    thread = threading.Thread(target=instance.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not instance.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            pytest.fail("the HTTP server did not start")
        time.sleep(0.05)
    port = instance.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    instance.should_exit = True
    thread.join(timeout=10)


def _post(url: str, authorization: str | None = None, **headers: str) -> httpx2.Response:
    headers = {"Accept": "application/json, text/event-stream", **headers}
    if authorization is not None:
        headers["Authorization"] = authorization
    return httpx2.post(url, json=INITIALIZE, headers=headers, timeout=30)


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        f"Bearer {WRONG}",
        f"Bearer {TOKEN}x",
        f"Bearer {TOKEN[:-1]}",
        f"Bearer {TOKEN},{ROTATED}",
        "Bearer",
        f"Basic {TOKEN}",
        TOKEN,
    ],
    ids=["missing", "wrong", "longer", "shorter", "both", "empty", "basic", "no-scheme"],
)
def test_a_request_without_a_configured_bearer_gets_401(base_url, authorization):
    response = _post(f"{base_url}/mcp", authorization)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_the_gate_stands_in_front_of_every_path_and_protocol_era(base_url):
    # Paths the SDK does not route, including where an OAuth client looks first.
    for path in ("/", "/.well-known/oauth-protected-resource", "/mcp/"):
        assert httpx2.get(f"{base_url}{path}", timeout=30).status_code == 401
    # The SDK answers a 2026-07-28 request on its own path, whatever the flags.
    modern = _post(f"{base_url}/mcp", **{"MCP-Protocol-Version": "2026-07-28"})
    assert modern.status_code == 401
    # With the token, only /mcp is there.
    ok = {"Authorization": f"Bearer {TOKEN}"}
    assert httpx2.get(f"{base_url}/", headers=ok, timeout=30).status_code == 404


@pytest.mark.parametrize(
    "authorization",
    [f"bearer {TOKEN}", f"BEARER {TOKEN}", f"Bearer  {TOKEN}"],
    ids=["lower", "upper", "two-spaces"],
)
def test_the_scheme_is_case_insensitive_and_spacing_is_tolerated(base_url, authorization):
    # RFC 6750: the scheme is case-insensitive and is followed by one or more spaces.
    assert _post(f"{base_url}/mcp", authorization).status_code == 200


@pytest.mark.parametrize("first, second", [(TOKEN, WRONG), (WRONG, TOKEN)])
def test_two_authorization_headers_are_refused(base_url, first, second):
    headers = [
        ("Accept", "application/json, text/event-stream"),
        ("Authorization", f"Bearer {first}"),
        ("Authorization", f"Bearer {second}"),
    ]
    response = httpx2.post(f"{base_url}/mcp", json=INITIALIZE, headers=headers, timeout=30)

    assert response.status_code == 401


def test_a_loopback_bind_keeps_the_sdks_dns_rebinding_guard(base_url):
    # A page that rebinds its own name to 127.0.0.1 still sends its own Host.
    response = _post(f"{base_url}/mcp", f"Bearer {TOKEN}", Host="mcp.example.com")

    assert response.status_code == 421


@pytest.mark.asyncio
async def test_a_bind_other_machines_can_reach_accepts_the_proxys_host():
    """Behind a reverse proxy, ``Host`` is the public name.

    The SDK applies its loopback-only Host check to whatever ``host`` it is
    given, defaulting to 127.0.0.1, so the bind address has to reach it or every
    proxied request to a 0.0.0.0 bind gets 421. Driven in-process, so the test
    never listens on a public interface.
    """
    app = http_transport.build_app(server.mcp, HttpSettings(host="0.0.0.0"))
    transport = httpx2.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx2.AsyncClient(transport=transport, base_url="https://mcp.example.com") as c:
            response = await c.post(
                "/mcp", json=INITIALIZE, headers={"Accept": "application/json, text/event-stream"}
            )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_only_http_requests_are_ever_passed_on():
    reached, sent = [], []

    async def app(scope, receive, send):
        reached.append(scope["type"])

    async def send(message):
        sent.append(message)

    gate = http_transport.BearerTokenMiddleware(app, (TOKEN,))
    headers = [(b"authorization", f"Bearer {TOKEN}".encode())]
    await gate({"type": "websocket", "headers": headers}, None, send)
    await gate({"type": "http", "headers": headers}, None, send)

    assert reached == ["http"]
    assert sent == []


def test_the_server_is_stateless_and_answers_json(base_url):
    response = _post(f"{base_url}/mcp", f"Bearer {TOKEN}")

    assert response.status_code == 200
    assert "mcp-session-id" not in response.headers
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["result"]["serverInfo"]["name"] == "outlook-mcp"


@pytest.mark.asyncio
@pytest.mark.parametrize("token", [TOKEN, ROTATED], ids=["first", "rotated"])
async def test_the_right_bearer_lists_the_same_surface_as_stdio(base_url, token):
    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}) as http:
        transport = streamable_http_client(f"{base_url}/mcp", http_client=http)
        # "legacy" is the initialize handshake today's clients use.
        async with Client(transport, mode="legacy") as client:
            over_http = (await client.list_tools()).tools
    async with Client(server.mcp) as client:
        in_process = (await client.list_tools()).tools

    def dump(tools):
        return [t.model_dump(exclude_none=True, by_alias=True) for t in tools]

    # The surface test_tool_surface_budget.py measures, unchanged by the transport.
    assert over_http
    assert dump(over_http) == dump(in_process)


# ── The real entrypoint, in its own process ─────────────────────────────


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_the_entrypoint_serves_and_logs_no_token_or_request_url(tmp_path):
    """A fresh process, because this is about what a real start configures.

    pytest's log capture leaves the root logger with handlers before the
    server is imported, so in-process logging is not what an operator gets
    (see test_request_urls_are_not_logged). Everything the process writes to
    stdout or stderr is the log here.
    """
    port = _free_port()
    env = dict(os.environ)
    env.update(
        {
            "OUTLOOK_MCP_CONFIG_DIR": str(tmp_path),
            TRANSPORT_ENV: "streamable-http",
            PORT_ENV: str(port),
            TOKEN_ENV: TOKEN,
        }
    )
    env.pop(HOST_ENV, None)
    proc = subprocess.Popen(
        [sys.executable, "-c", "from outlook_mcp.server import main; main()"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    url = f"http://127.0.0.1:{port}/mcp?q=find-me"
    try:
        deadline = time.monotonic() + 60
        while True:
            if proc.poll() is not None:
                pytest.fail(f"the server exited: {proc.communicate()[1]}")
            try:
                refused = _post(url, f"Bearer {WRONG}")
                break
            except httpx2.TransportError:
                if time.monotonic() > deadline:
                    pytest.fail("the server did not start listening")
                time.sleep(0.2)
        served = _post(url, f"Bearer {TOKEN}")
    finally:
        proc.terminate()
        out, err = proc.communicate(timeout=30)

    assert refused.status_code == 401
    assert served.status_code == 200
    logged = out + err
    for secret in (TOKEN, WRONG, "find-me", "/mcp", f"127.0.0.1:{port}"):
        assert secret not in logged
