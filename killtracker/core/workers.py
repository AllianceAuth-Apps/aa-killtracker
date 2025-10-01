"""Allows tasks to find out whether their worker is currently shutting down.

This enables long running tasks to abort early,
which helps to speed up a warm worker shutdown.
"""

from celery import Task

from django.core.cache import cache

from allianceauth.services.hooks import get_extension_logger
from app_utils.logging import LoggerAddTag

from killtracker import __title__

_TIMEOUT_SECONDS = 120

logger = LoggerAddTag(get_extension_logger(__name__), __title__)


def state_reset(hostname: str) -> None:
    """Resets the shutting down state for a worker."""
    cache.delete(_make_key(hostname))


def state_set(hostname: str) -> None:
    """Sets a worker into the shutting down state."""
    cache.set(_make_key(hostname), "shutting down", timeout=_TIMEOUT_SECONDS)


def is_shutting_down(task: Task) -> bool:
    """Reports whether the worker of a celery task is currently shutting down."""
    try:
        hostname = str(task.request.hostname)
    except (AttributeError, TypeError, ValueError):
        logger.warning("Failed to retrieve hostname: %s", task)
        return False

    if cache.get(_make_key(hostname)) is None:
        return False

    return True


def _make_key(hostname: str) -> str:
    return f"killtracker-worker-shutting-down-{hostname}"
