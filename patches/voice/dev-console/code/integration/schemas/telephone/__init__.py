"""The telephony channel: one module per provider, registered in ``SCHEMAS``."""

from typing import Dict

from integration.schemas.base import ProviderSchemas
from integration.schemas.telephone import vobiz

CHANNEL = "telephony"

SCHEMAS: Dict[str, ProviderSchemas] = {
    vobiz.PROVIDER: vobiz.SCHEMA,
}

PROVIDERS = tuple(SCHEMAS)
