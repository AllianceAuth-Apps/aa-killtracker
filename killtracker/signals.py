"""Module signals connects to celery signals."""

# pylint: disable=missing-function-docstring

from celery import signals

from allianceauth.services.hooks import get_extension_logger
from app_utils.logging import LoggerAddTag

from killtracker import __title__
from killtracker.core import workers

logger = LoggerAddTag(get_extension_logger(__name__), __title__)


@signals.worker_ready.connect
def worker_ready_handler(sender, **kwargs):
    workers.state_reset(sender.hostname)
    logger.debug("worker_ready: %s", sender.hostname)


@signals.worker_shutting_down.connect
def worker_shutting_down_handler(sender, **kwargs):
    workers.state_set(sender)
    logger.debug("worker_shutting_down: %s", sender)


@signals.worker_shutdown.connect
def worker_shutdown_handler(sender, **kwargs):
    workers.state_reset(sender.hostname)
    logger.debug("worker_shutdown: %s", sender.hostname)
