"""Read-only checks of Graph's invitation-to-calendar relationship.

Harvest IDs from at most 50 messages and skip when the mailbox lacks the needed
message type or a surviving association. No fixture sends or changes anything.
"""

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


@pytest.fixture
async def message_sample(real_graph_client):
    page = await real_graph_client.sdk_client.me.messages.get(
        request_configuration=build_request_config(
            MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters,
            {"$select": "id", "$top": 50},
        )
    )
    return page.value or []


async def test_plain_mail_has_no_event_rather_than_a_graph_error(real_graph_client, message_sample):
    """The subtype expand must be accepted even when the message is ordinary mail."""
    message = next((m for m in message_sample if type(m) is Message and m.id), None)
    if message is None:
        pytest.skip("No ordinary mail among the first 50 messages")

    with pytest.raises(ValueError, match="no associated calendar event"):
        await get_event(real_graph_client.sdk_client, message_id=message.id)


async def test_invitation_resolves_to_the_mailbox_event(real_graph_client, message_sample):
    """An expanded invitation must identify an event readable through this user's /me."""
    sdk = real_graph_client.sdk_client
    candidates = [m for m in message_sample if isinstance(m, EventMessageRequest) and m.id]
    for message in candidates:
        expanded = await sdk.me.messages.by_message_id(message.id).get(
            request_configuration=build_request_config(
                MessageItemRequestBuilder.MessageItemRequestBuilderGetQueryParameters,
                {"$expand": "microsoft.graph.eventMessage/event"},
            )
        )
        associated = getattr(expanded, "event", None)
        if associated is None or not associated.id:
            continue  # Cancelled or removed meetings need not have a calendar event.

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
        return

    pytest.skip("No invitation with a calendar event among the first 50 messages")
