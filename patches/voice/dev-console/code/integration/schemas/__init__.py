"""Credential schemas, one package per channel; these functions deal only in blobs, not rows."""

from types import ModuleType
from typing import Any, Dict, Optional, Tuple

from pydantic import ValidationError

from integration.schemas import telephone, whatsapp
from integration.schemas.base import (
    ChannelCredentials,
    ChannelPublic,
    ChannelUpdate,
    ProviderSchemas,
)

# `requests` is not re-exported here: it imports `schema_for`, so that would be circular.

CHANNELS: Dict[str, ModuleType] = {
    whatsapp.CHANNEL: whatsapp,
    telephone.CHANNEL: telephone,
}


class UnsupportedProvider(ValueError):
    """This channel has no schema for that provider."""


def providers_for(channel: str) -> Tuple[str, ...]:
    """Providers this channel supports; empty when the channel has no package yet."""
    package = CHANNELS.get(channel)
    return tuple(getattr(package, "PROVIDERS", ())) if package else ()


def schema_for(channel: str, provider: str) -> Optional[ProviderSchemas]:
    """The provider's models, or None when the channel has no package."""
    package = CHANNELS.get(channel)
    if package is None:
        return None
    try:
        return package.SCHEMAS[provider]
    except KeyError:
        raise UnsupportedProvider(
            f"{provider!r} is not a {channel} provider; expected one of "
            f"{', '.join(package.PROVIDERS)}"
        ) from None


def validate(channel: str, provider: str, raw: dict) -> Tuple[dict, Optional[str]]:
    """Validate a full blob; returns ``(credentials, uid)``."""
    schema = schema_for(channel, provider)
    if schema is None:
        # Declared channel with no schema yet: store unread, claim no account id.
        return dict(raw or {}), None

    parsed = schema.parse(raw)
    return parsed.model_dump(), parsed.uid()


def merge(
    channel: str, provider: str, stored: dict, patch: dict
) -> Tuple[dict, Optional[str]]:
    """Apply a partial update; the provider's Update model forbids identity fields."""
    schema = schema_for(channel, provider)
    if schema is None:
        merged = {**(stored or {}), **(patch or {})}
        return merged, None

    allowed = schema.patch(patch)
    merged = {**(stored or {}), **allowed}

    parsed = schema.parse(merged)
    return parsed.model_dump(), parsed.uid()


def public(channel: str, provider: str, raw: dict) -> dict:
    """Non-secret subset of a blob. Never raises, so one bad row can't break a listing."""
    try:
        schema = schema_for(channel, provider)
    except UnsupportedProvider:
        return {}
    if schema is None:
        return {}
    try:
        return schema.readable(raw)
    except ValidationError:
        return {}


__all__ = [
    "CHANNELS",
    "ChannelCredentials",
    "ChannelPublic",
    "ChannelUpdate",
    "ProviderSchemas",
    "UnsupportedProvider",
    "merge",
    "providers_for",
    "public",
    "schema_for",
    "validate",
]
