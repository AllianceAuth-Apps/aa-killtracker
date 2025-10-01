import logging
from typing import Any, Dict

from app_utils.allianceauth import get_redis_client

logger = logging.getLogger(__name__)


def reset_celery_once_locks():
    """Reset celery once locks for given tasks."""
    r = get_redis_client()
    app_label = "killtracker"
    if keys := r.keys(f":?:qo_{app_label}.*"):
        deleted_count = r.delete(*keys)
        logger.info("Removed %d stuck celery once keys", deleted_count)
    else:
        deleted_count = 0


class CacheFake:
    """A fake for replacing Django's cache in tests."""

    def __init__(self):
        self._cache: Dict[str, Any] = {}

    def clear(self) -> None:
        self._cache.clear()

    def delete(self, key: str, version: int = None) -> None:
        try:
            del self._cache[key]
        except KeyError:
            pass

    def get(self, key: str, default: Any = None, version: int = None) -> Any:
        try:
            return self._cache[key]
        except KeyError:
            return default

    def set(
        self, key: str, value: Any, timeout: int = None, version: int = None
    ) -> None:
        self._cache[key] = value
