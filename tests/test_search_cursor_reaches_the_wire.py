"""Does an ``outlook_search_mail`` cursor reach the wire?

Graph pages a message ``$search`` with ``$skiptoken``, never ``$skip`` (a
``$search`` with ``$skip`` is ``400 SearchWithSkip``). ``wrap_nextlink`` turns
that link into a ``{"skiptoken": ...}`` cursor and ``apply_pagination`` puts
the token back as ``$skiptoken`` — and then ``build_request_config`` drops it,
because no typed ``users/*`` query-parameters class has a ``skiptoken`` field
and their URL templates stop at ``$top``. Page two went out as page one, with
``has_more`` still true. A mock of ``.get()`` cannot see that: the dict it is
handed still says ``$skiptoken``. So these tests build the client the way
``msgraph`` does, hand it a mock transport, and assert on the URL the real
request pipeline sends — the way ``test_me_rewrite_reaches_the_wire.py`` does
for ``/me``.

The cursor also carries the folder the search ran in, as ``list_events``'s
carries its calendar, so a later page cannot drift to another folder.
"""

from __future__ import annotations

import inspect
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from azure.core.credentials import AccessToken
from kiota_authentication_azure.azure_identity_authentication_provider import (
    AzureIdentityAuthenticationProvider,
)
from msgraph import GraphServiceClient
from msgraph import graph_request_adapter as _gra
from msgraph_core import GraphClientFactory

from outlook_mcp.pagination import decode_cursor_payload, encode_cursor_payload
from outlook_mcp.tools import mail_read
from outlook_mcp.tools.mail_read import SUMMARY_SELECT, search_mail

ME = "https://graph.microsoft.com/v1.0/me"
# Graph sends the token percent-encoded; it must come back out exactly as sent.
TOKEN = "MSZZVlhKUlZXVmhFV1hjeE9VZGhWMHA2V1d0R2NHUnRWbmxaZDFFOVBRPT0="
TOKEN_ON_THE_WIRE = "MSZZVlhKUlZXVmhFV1hjeE9VZGhWMHA2V1d0R2NHUnRWbmxaZDFFOVBRPT0%3D"


class _FakeCredential:
    def get_token(self, *args, **kwargs):
        return AccessToken("not-a-real-token", 9_999_999_999)


def _graph(pages: list[dict]) -> tuple[GraphServiceClient, list[httpx.URL]]:
    """A real SDK client whose transport answers with ``pages`` in order.

    Returns the client and the list of URLs it sent, in order.
    """
    sent: list[httpx.URL] = []
    queue = list(pages)

    async def transport(request: httpx.Request) -> httpx.Response:
        sent.append(request.url)
        return httpx.Response(200, json=queue.pop(0))

    factory = GraphClientFactory.create_with_default_middleware
    kwargs = {}
    params = inspect.signature(factory).parameters
    if "options" in params:
        kwargs["options"] = getattr(_gra, "options", None)
    if "client" in params:
        kwargs["client"] = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    auth = AzureIdentityAuthenticationProvider(
        _FakeCredential(), scopes=["https://graph.microsoft.com/.default"]
    )
    client = GraphServiceClient(request_adapter=_gra.GraphRequestAdapter(auth, factory(**kwargs)))
    return client, sent


def _page(first: int, rows: int, next_link: str | None) -> dict:
    page: dict = {
        "value": [
            {"id": f"m{first + i}", "subject": "s", "receivedDateTime": "2026-01-01T00:00:00Z"}
            for i in range(rows)
        ]
    }
    if next_link:
        page["@odata.nextLink"] = next_link
    return page


def _next(path: str, token: str = TOKEN_ON_THE_WIRE) -> str:
    return f"{ME}/{path}?$search=%22budget%22&$top=25&$select=id&$skiptoken={token}"


def _query(url: httpx.URL) -> dict[str, list[str]]:
    return parse_qs(urlsplit(str(url)).query)


@pytest.mark.asyncio
async def test_the_cursor_sends_graphs_skiptoken():
    client, sent = _graph([_page(0, 25, _next("messages")), _page(25, 25, None)])

    first = await search_mail(client, query="budget", count=25)
    second = await search_mail(client, query="budget", count=25, cursor=first["cursor"])

    assert first["has_more"] is True
    assert [m["id"] for m in second["messages"]] == [f"m{i}" for i in range(25, 50)]
    url = sent[1]
    assert str(url).startswith(f"{ME}/messages?"), url
    assert _query(url) == {
        "$search": ['"budget"'],
        "$select": [SUMMARY_SELECT],
        "$top": ["25"],
        "$skiptoken": [TOKEN],
    }, (
        "page two is not page one plus Graph's $skiptoken — a dropped token re-fetches "
        "page one forever"
    )
    assert TOKEN_ON_THE_WIRE in str(url), "the token was not re-encoded the way Graph sent it"


@pytest.mark.asyncio
async def test_the_cursor_stays_in_the_folder_it_searched():
    client, sent = _graph(
        [_page(0, 25, _next("mailFolders('inbox')/messages")), _page(25, 1, None)]
    )

    first = await search_mail(client, query="budget", count=25, folder="inbox")
    await search_mail(client, query="budget", count=25, folder="inbox", cursor=first["cursor"])

    assert str(sent[1]).startswith(f"{ME}/mailFolders/inbox/messages?"), sent[1]
    assert _query(sent[1])["$skiptoken"] == [TOKEN]


@pytest.mark.asyncio
async def test_a_token_cannot_add_anything_to_the_request():
    """The token is one query value: whatever it holds, nothing else changes."""
    hostile = "x&$search=%22everything%22&$top=1000#"
    cursor = encode_cursor_payload({"skiptoken": hostile})
    client, sent = _graph([_page(0, 1, None)])

    await search_mail(client, query="budget", count=25, cursor=cursor)

    assert str(sent[0]).startswith(f"{ME}/messages?")
    query = _query(sent[0])
    assert query["$skiptoken"] == [hostile]
    assert query["$search"] == ['"budget"']
    assert query["$top"] == ["25"]


@pytest.mark.parametrize(
    "payload",
    [
        {"skiptoken": 7},
        {"skiptoken": ""},
        {"skiptoken": "t", "folder": 5},
        {"skiptoken": "t", "folder": "inbox/../../users/someone-else"},
    ],
)
@pytest.mark.asyncio
async def test_a_tampered_cursor_is_refused_before_any_request(payload):
    client, sent = _graph([])
    with pytest.raises(ValueError):
        await search_mail(client, query="budget", cursor=encode_cursor_payload(payload))
    assert sent == []


def _resolver(monkeypatch) -> list[str]:
    """Stand in for the folder lookup (a Graph round trip) and record each name asked."""
    asked: list[str] = []

    async def resolve(graph_client, name):
        asked.append(name)
        return "AAMkFolder1"

    monkeypatch.setattr(mail_read, "resolve_folder_id", resolve)
    return asked


@pytest.mark.asyncio
async def test_a_bad_token_is_refused_before_the_folder_is_looked_up(monkeypatch):
    asked = _resolver(monkeypatch)
    client, sent = _graph([])

    with pytest.raises(ValueError, match="Invalid pagination cursor"):
        await search_mail(
            client,
            query="budget",
            folder="Projects",
            cursor=encode_cursor_payload({"skiptoken": 7}),
        )

    assert asked == [] and sent == []


@pytest.mark.asyncio
async def test_the_cursor_carries_the_folder_it_searched(monkeypatch):
    """Page two goes to page one's folder: not looked up again, not dropped, not swapped."""
    asked = _resolver(monkeypatch)
    folder_path = f"{ME}/mailFolders/AAMkFolder1/messages?"
    client, sent = _graph(
        [
            _page(0, 25, _next("mailFolders('AAMkFolder1')/messages")),
            _page(25, 25, _next("mailFolders('AAMkFolder1')/messages")),
            _page(50, 1, None),
        ]
    )

    first = await search_mail(client, query="budget", count=25, folder="Projects")
    assert decode_cursor_payload(first["cursor"])["folder"] == "AAMkFolder1"
    second = await search_mail(client, query="budget", count=25, cursor=first["cursor"])
    await search_mail(client, query="budget", count=25, folder="Elsewhere", cursor=second["cursor"])

    assert asked == ["Projects"]
    assert all(str(url).startswith(folder_path) for url in sent), sent


@pytest.mark.asyncio
async def test_a_cursor_from_a_search_of_all_mail_stays_there(monkeypatch):
    asked = _resolver(monkeypatch)
    client, sent = _graph([_page(0, 25, _next("messages")), _page(25, 1, None)])

    first = await search_mail(client, query="budget", count=25)
    assert decode_cursor_payload(first["cursor"])["folder"] is None
    await search_mail(client, query="budget", count=25, folder="Projects", cursor=first["cursor"])

    assert asked == []
    assert str(sent[1]).startswith(f"{ME}/messages?"), sent[1]
