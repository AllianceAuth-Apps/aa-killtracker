"""A module with helpers for the core package."""

import datetime as dt
from typing import Optional

from django.core.cache import cache

from allianceauth.services.hooks import get_extension_logger
from app_utils.logging import LoggerAddTag

from killtracker import __title__

logger = LoggerAddTag(get_extension_logger(__name__), __title__)


def cache_get_timestamp(
    key: str, fallback: Optional[dt.datetime]
) -> Optional[dt.datetime]:
    """Returns a timestamp from cache when it exists
    or None when it does not exist
    or a fallback in case the cache value exists, but can not be parsed.
    """
    v = cache.get(key)
    if v is None:
        return None
    try:
        return dt.datetime.fromisoformat(v)
    except (TypeError, ValueError):
        cache.delete(key)
        logger.warning("%s: unable to parse timestamp from cache. Using fallback", key)
        return fallback


def cache_set_timestamp(key: str, ts: dt.datetime, timeout: int = 60):
    """Sets a timestamp as cache value."""
    cache.set(key, ts.isoformat(), timeout=timeout)
