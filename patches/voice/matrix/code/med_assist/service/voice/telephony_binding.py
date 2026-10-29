"""
Which agent answers a phone number.

The console registers a number as an ``integrations`` row (channel ``telephony``,
provider ``vobiz``) and binds it to one agent through ``product_integrations``.
Both tables live in the Postgres that matrix already reads agent configuration
from, so the lookup is one query, like ``agent_config_utils``. The console owns
writing them; this module only reads.

The integration uuid in the answer URL is the access control, as it is for
WhatsApp numbers in doot: it is unguessable, and an unbound, paused, archived
or foreign uuid answers nothing.
"""

import base64
from typing import Optional
from uuid import UUID

from echo_agents.utils.pg_wrapper import get_pg_client

from common.utils import get_logger
from med_assist.service.voice import handover_settings
from med_assist.service.voice.handover_settings import HandoverSettings

logger = get_logger("med_assist.service.voice.telephony_binding")

CHANNEL = "telephony"
PROVIDER = "vobiz"
PRODUCT = "agent"

# One row per number: LEFT JOIN so "registered but not bound" is told apart from "unknown".
_SQL = (
    "SELECT i.workspace_id, i.channel, i.provider, i.is_active, i.archived_at, "
    "       p.product, p.product_id, p.is_active AS binding_active, p.config "
    "FROM integrations i "
    "LEFT JOIN product_integrations p ON p.integration_id = i.id "
    "WHERE i.uuid = $1"
)


class NumberNotServed(Exception):
    """No agent should answer this number. ``reason`` is for logs, never for the caller."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _workspace_of(agent_id: str) -> Optional[str]:
    """Workspace id inside an agent id (base64 of ``<uuid>#<workspace>``), or None."""
    try:
        return base64.b64decode(agent_id).decode("utf-8").split("#", 1)[1]
    except Exception:
        return None


async def _serving_row(integration_uuid: str) -> dict:
    """The number's row if an agent should answer it, else raise ``NumberNotServed``."""
    try:
        number_uuid = UUID(integration_uuid)
    except ValueError:
        raise NumberNotServed("malformed uuid") from None

    row = await get_pg_client().fetch_one(_SQL, number_uuid)
    if not row:
        raise NumberNotServed("unknown number")
    if row["channel"] != CHANNEL or row["provider"] != PROVIDER:
        raise NumberNotServed("not a vobiz telephony number")
    if not row["is_active"] or row["archived_at"] is not None:
        raise NumberNotServed("number is not active")
    if row["product"] is None:
        raise NumberNotServed("number is not bound to a product")
    if row["product"] != PRODUCT:
        raise NumberNotServed(f"number is bound to {row['product']}, not an agent")
    if not row["binding_active"]:
        raise NumberNotServed("binding is paused")

    # The binding API does not check that the agent belongs to the number's
    # workspace, so check it here: a number must never open another workspace's agent.
    if _workspace_of(row["product_id"]) != row["workspace_id"]:
        raise NumberNotServed("agent belongs to another workspace")
    return row


async def agent_for_number(integration_uuid: str) -> str:
    """The agent id bound to this number, or raise ``NumberNotServed``."""
    return (await _serving_row(integration_uuid))["product_id"]


async def handover_for_number(integration_uuid: str) -> Optional[HandoverSettings]:
    """Where this number's calls can be handed to a person, or None (not configured, or not served)."""
    try:
        row = await _serving_row(integration_uuid)
    except NumberNotServed:
        return None
    return handover_settings.from_binding_config(row["config"])
