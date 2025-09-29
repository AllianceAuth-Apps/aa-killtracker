import datetime as dt
from http import HTTPStatus
from time import sleep

import dhooks_lite

from django.utils.timezone import now

from allianceauth.services.hooks import get_extension_logger
from app_utils.logging import LoggerAddTag

from killtracker import APP_NAME, HOMEPAGE_URL, __title__, __version__
from killtracker.app_settings import KILLTRACKER_DISCORD_SEND_DELAY
from killtracker.core.discord_messages import DiscordMessage
from killtracker.core.helper import cache_get_timestamp, cache_set_timestamp

logger = LoggerAddTag(get_extension_logger(__name__), __title__)

_DEFAULT_429_TIMEOUT = 600


class HTTPError(Exception):
    def __init__(self, status_code: int):
        self.status_code = status_code


class WebhookTooManyRequests(Exception):
    """Webhook is temporarily blocked."""

    def __init__(self, retry_at: dt.datetime, is_original: bool = True):
        self.retry_at = retry_at
        self.is_original = is_original


def send_message_to_webhook(name: str, url: str, message: DiscordMessage) -> int:
    """Send a message to a Discord webhook and returns the ID of new message."""

    key_retry_at = f"killtracker-webhook-retry-at-{url}"
    retry_at = cache_get_timestamp(
        key_retry_at, now() + dt.timedelta(seconds=_DEFAULT_429_TIMEOUT)
    )
    if retry_at is not None and retry_at > now():
        raise WebhookTooManyRequests(retry_at=retry_at, is_original=False)

    key_last_request = f"killtracker-webhook-last-request-{url}"
    last_request = cache_get_timestamp(key_last_request, now())
    if last_request is not None:
        next_slot = last_request + dt.timedelta(seconds=KILLTRACKER_DISCORD_SEND_DELAY)
        seconds = (next_slot - now()).total_seconds()
        if seconds > 0:
            logger.debug(
                "%s: Waiting %f seconds for next free slot for webhook", name, seconds
            )
            sleep(seconds)

    hook = dhooks_lite.Webhook(
        url=url,
        user_agent=dhooks_lite.UserAgent(
            name=APP_NAME, url=HOMEPAGE_URL, version=__version__
        ),
    )
    response = hook.execute(
        content=message.content,
        embeds=message.embeds,
        username=message.username,
        avatar_url=message.avatar_url,
        wait_for_response=True,
        max_retries=0,  # we will handle retries ourselves
    )
    cache_set_timestamp(
        key_last_request,
        now(),
        timeout=KILLTRACKER_DISCORD_SEND_DELAY + 30,
    )
    logger.debug(
        "%s: Response from Discord for creating message from killmail %d: %s %s %s",
        name,
        message.killmail_id,
        response.status_code,
        response.headers,
        response.content,
    )
    if not response.status_ok:
        if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
            try:
                retry_after = int(response.headers["Retry-After"])
            except KeyError:
                retry_after = _DEFAULT_429_TIMEOUT
            retry_at = now() + dt.timedelta(seconds=retry_after)
            cache_set_timestamp(key_retry_at, retry_at, timeout=retry_after + 60)
            raise WebhookTooManyRequests(retry_at=retry_at, is_original=True)

        raise HTTPError(response.status_code)

    try:
        message_id = int(response.content.get("id"))
    except (AttributeError, ValueError):
        message_id = 0

    return message_id
