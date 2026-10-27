"""Read-only checks of Graph's invitation-to-calendar relationship.

Plain mail is checked on the first 50 messages. Invitations are rarer, so their
guard walks ID-only pages until it finds one with a surviving event, reading at most
1,000 messages. Each skips when the mailbox lacks what it needs, and the skip says how
much it read. No fixture sends or changes anything.
"""

from contextlib import aclosing

import pytest
from msgraph.generated.models.event_message_request import EventMessageRequest
from msgraph.generated.models.message import Message
from msgraph.generated.users.item.messages.item.message_item_request_builder import (
    MessageItemRequestBuilder,
)
from msgraph.generated.users.item.messages.messages_request_builder import MessagesRequestBuilder

from outlook_mcp.pagination import build_request_config
from outlook_mcp.tools.calendar_read import get_event

pytestmark = [pytest.mark.live, pytest.mark.asyncio]

PAGE_SIZE = 50
MAX_MESSAGES = 1_000


async def message_pages(sdk):
    """Yield ID-only message pages, newest first, until MAX_MESSAGES have been read."""
    page = await sdk.me.messages.get(
        request_configuration=build_request_config(
            MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters,
            {"$select": "id", "$top": PAGE_SIZE},
        )
    )
    read = 0
    while page is not None:
        messages = (page.value or [])[: MAX_MESSAGES - read]
        read += len(messages)
        yield messages
        if read >= MAX_MESSAGES or not page.odata_next_link:
            return
        page = await sdk.me.messages.with_url(page.odata_next_link).get()


@pytest.fixture
async def message_sample(real_graph_client):
    async with aclosing(message_pages(real_graph_client.sdk_client)) as pages:
        return await anext(pages, [])


async def test_plain_mail_has_no_event_rather_than_a_graph_error(real_graph_client, message_sample):
    """The subtype expand must be accepted even when the message is ordinary mail."""
    message = next((m for m in message_sample if type(m) is Message and m.id), None)
    if message is None:
        pytest.skip("No ordinary mail among the first 50 messages")

    with pytest.raises(ValueError, match="no associated calendar event"):
        await get_event(real_graph_client.sdk_client, message_id=message.id)


async def test_invitation_resolves_to_the_mailbox_event(real_graph_client):
    """An expanded invitation must identify an event readable through this user's /me."""
    sdk = real_graph_client.sdk_client
    read = invitations = 0
    async with aclosing(message_pages(sdk)) as pages:
        async for messages in pages:
            read += len(messages)
            for message in messages:
                if not isinstance(message, EventMessageRequest) or not message.id:
                    continue
                invitations += 1
                if await _resolves_to_current_event(sdk, message):
                    return

    pytest.skip(
        f"No invitation with a calendar event among the newest {read} messages "
        f"({invitations} invitations seen)"
    )


async def _resolves_to_current_event(sdk, message) -> bool:
    """Assert one invitation's result; False when its meeting has no calendar event."""
    expanded = await sdk.me.messages.by_message_id(message.id).get(
        request_configuration=build_request_config(
            MessageItemRequestBuilder.MessageItemRequestBuilderGetQueryParameters,
            {"$expand": "microsoft.graph.eventMessage/event"},
        )
    )
    associated = getattr(expanded, "event", None)
    if associated is None or not associated.id:
        return False  # Cancelled or removed meetings need not have a calendar event.

    current = await sdk.me.events.by_event_id(associated.id).get()
    result = await get_event(sdk, message_id=message.id)

    assert result["id"] == current.id == associated.id
    assert result["is_organizer"] is current.is_organizer
    assert result["allow_new_time_proposals"] is current.allow_new_time_proposals
    assert result["is_cancelled"] is current.is_cancelled
    assert result["invitation"] == {
        "message_id": message.id,
        "is_out_of_date": expanded.is_out_of_date,
    }
    return True
