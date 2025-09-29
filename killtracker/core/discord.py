"""Send messages to Discord webhooks."""

import datetime as dt
import json
from copy import copy
from dataclasses import dataclass
from http import HTTPStatus
from time import sleep
from typing import List, Optional

import dhooks_lite

from django.utils.timezone import now

from allianceauth.services.hooks import get_extension_logger
from app_utils.json import JSONDateTimeDecoder, JSONDateTimeEncoder
from app_utils.logging import LoggerAddTag

from killtracker import APP_NAME, HOMEPAGE_URL, __title__, __version__
from killtracker.app_settings import KILLTRACKER_DISCORD_SEND_DELAY
from killtracker.core.helper import cache_get_timestamp, cache_set_timestamp

_DEFAULT_429_TIMEOUT = 600

logger = LoggerAddTag(get_extension_logger(__name__), __title__)


class HTTPError(Exception):
    """A HTTP error."""

    def __init__(self, status_code: int):
        self.status_code = status_code


class WebhookTooManyRequests(Exception):
    """Webhook is temporarily blocked."""

    def __init__(self, retry_at: dt.datetime, is_original: bool = True):
        self.retry_at = retry_at
        self.is_original = is_original


@dataclass
class DiscordMessage:
    """A Discord message created from a Killmail."""

    avatar_url: Optional[str] = None
    content: Optional[str] = None
    embeds: Optional[List[dhooks_lite.Embed]] = None
    killmail_id: int = 0  # Killmail ID this message from created from
    tts: Optional[bool] = None
    username: Optional[str] = None

    def __post_init__(self):
        if not self.content and not self.embeds:
            raise ValueError("Message must have content or embeds to be valid")

    def to_json(self) -> str:
        """Converts a Discord message into a JSON object and returns it."""

        if self.embeds:
            embeds_list = [obj.asdict() for obj in self.embeds]
        else:
            embeds_list = None

        message = {}
        if self.killmail_id:
            message["killmail_id"] = self.killmail_id
        if self.content:
            message["content"] = self.content
        if embeds_list:
            message["embeds"] = embeds_list
        if self.tts:
            message["tts"] = self.tts
        if self.username:
            message["username"] = self.username
        if self.avatar_url:
            message["avatar_url"] = self.avatar_url

        return json.dumps(message, cls=JSONDateTimeEncoder)

    @classmethod
    def from_json(cls, s: str) -> "DiscordMessage":
        """Creates a DiscordMessage object from an JSON object and returns it."""
        message1: dict = json.loads(s, cls=JSONDateTimeDecoder)
        message2 = copy(message1)
        if message1.get("embeds"):
            message2["embeds"] = [
                dhooks_lite.Embed.from_dict(embed_dict)
                for embed_dict in message1.get("embeds")
            ]
        else:
            message2["embeds"] = None
        return cls(**message2)


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
