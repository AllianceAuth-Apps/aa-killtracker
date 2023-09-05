"""ESI provider for killtracker."""

from esi.clients import EsiClientProvider

from allianceauth.services.hooks import get_extension_logger
from app_utils.logging import LoggerAddTag

from . import USER_AGENT_TEXT, __title__

logger = LoggerAddTag(get_extension_logger(__name__), __title__)

esi = EsiClientProvider(app_info_text=USER_AGENT_TEXT)
