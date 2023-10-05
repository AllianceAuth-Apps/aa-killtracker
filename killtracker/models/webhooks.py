"""Webhooks models for killtracker."""

import json
from typing import List, Optional

import dhooks_lite
from simple_mq import SimpleMQ

from django.core.cache import cache
from django.db import models
from django.utils.translation import gettext_lazy as _

from allianceauth.services.hooks import get_extension_logger
from app_utils.allianceauth import get_redis_client
from app_utils.json import JSONDateTimeDecoder, JSONDateTimeEncoder
from app_utils.logging import LoggerAddTag
from app_utils.urls import static_file_absolute_url

from killtracker import APP_NAME, HOMEPAGE_URL, __title__, __version__
from killtracker.app_settings import KILLTRACKER_WEBHOOK_SET_AVATAR
from killtracker.exceptions import WebhookTooManyRequests
from killtracker.managers import WebhookManager

logger = LoggerAddTag(get_extension_logger(__name__), __title__)


class Webhook(models.Model):
    """A webhook to receive messages"""

    HTTP_TOO_MANY_REQUESTS = 429

    class WebhookType(models.IntegerChoices):
        """A webhook type."""

        DISCORD = 1, _("Discord Webhook")

    name = models.CharField(
        max_length=64, unique=True, help_text="short name to identify this webhook"
    )
    webhook_type = models.IntegerField(
        choices=WebhookType.choices,
        default=WebhookType.DISCORD,
        help_text="type of this webhook",
    )
    url = models.CharField(
        max_length=255,
        unique=True,
        help_text=(
            "URL of this webhook, e.g. "
            "https://discordapp.com/api/webhooks/123456/abcdef"
        ),
    )
    notes = models.TextField(
        blank=True,
        help_text="you can add notes about this webhook here if you want",
    )
    is_enabled = models.BooleanField(
        default=True,
        db_index=True,
        help_text="whether notifications are currently sent to this webhook",
    )
    objects = WebhookManager()

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.main_queue = self._create_queue("main")
        self.error_queue = self._create_queue("error")

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id={self.id}, name='{self.name}')"  # type: ignore

    def __getstate__(self):
        # Copy the object's state from self.__dict__ which contains
        # all our instance attributes. Always use the dict.copy()
        # method to avoid modifying the original state.
        state = self.__dict__.copy()
        # Remove the unpicklable entries.
        del state["main_queue"]
        del state["error_queue"]
        return state

    def __setstate__(self, state):
        # Restore instance attributes (i.e., filename and lineno).
        self.__dict__.update(state)
        # Restore the previously opened file's state. To do so, we need to
        # reopen it and read from it until the line count is restored.
        self.main_queue = self._create_queue("main")
        self.error_queue = self._create_queue("error")

    def save(self, *args, **kwargs):
        is_new = self.id is None  # type: ignore
        super().save(*args, **kwargs)
        if is_new:
            self.main_queue = self._create_queue("main")
            self.error_queue = self._create_queue("error")

    def _create_queue(self, suffix: str) -> Optional[SimpleMQ]:
        redis_client = get_redis_client()
        return (
            SimpleMQ(redis_client, f"{__title__}_webhook_{self.pk}_{suffix}")
            if self.pk
            else None
        )

    def reset_failed_messages(self) -> int:
        """moves all messages from error queue into main queue.
        returns number of moved messages.
        """
        counter = 0
        if self.error_queue and self.main_queue:
            while True:
                message = self.error_queue.dequeue()
                if message is None:
                    break

                self.main_queue.enqueue(message)
                counter += 1

        return counter

    def enqueue_message(
        self,
        content: Optional[str] = None,
        embeds: Optional[List[dhooks_lite.Embed]] = None,
        tts: Optional[bool] = None,
        username: Optional[str] = None,
        avatar_url: Optional[str] = None,
    ) -> int:
        """Enqueues a message to be send with this webhook"""
        if not self.main_queue:
            return 0

        username = __title__ if KILLTRACKER_WEBHOOK_SET_AVATAR else username
        brand_url = static_file_absolute_url("killtracker/killtracker_logo.png")
        avatar_url = brand_url if KILLTRACKER_WEBHOOK_SET_AVATAR else avatar_url
        return self.main_queue.enqueue(
            self._discord_message_asjson(
                content=content,
                embeds=embeds,
                tts=tts,
                username=username,
                avatar_url=avatar_url,
            )
        )

    @staticmethod
    def _discord_message_asjson(
        content: Optional[str] = None,
        embeds: Optional[List[dhooks_lite.Embed]] = None,
        tts: Optional[bool] = None,
        username: Optional[str] = None,
        avatar_url: Optional[str] = None,
    ) -> str:
        """Converts a Discord message to JSON and returns it

        Raises ValueError if message is incomplete
        """
        if not content and not embeds:
            raise ValueError("Message must have content or embeds to be valid")

        if embeds:
            embeds_list = [obj.asdict() for obj in embeds]
        else:
            embeds_list = None

        message = {}
        if content:
            message["content"] = content
        if embeds_list:
            message["embeds"] = embeds_list
        if tts:
            message["tts"] = tts
        if username:
            message["username"] = username
        if avatar_url:
            message["avatar_url"] = avatar_url

        return json.dumps(message, cls=JSONDateTimeEncoder)

    def send_message_to_webhook(self, message_json: str) -> dhooks_lite.WebhookResponse:
        """Send given message to webhook

        Params
            message_json: Discord message encoded in JSON
        """
        timeout = cache.ttl(self._blocked_cache_key())  # type: ignore
        if timeout:
            raise WebhookTooManyRequests(timeout)

        message = json.loads(message_json, cls=JSONDateTimeDecoder)
        if message.get("embeds"):
            embeds = [
                dhooks_lite.Embed.from_dict(embed_dict)
                for embed_dict in message.get("embeds")
            ]
        else:
            embeds = None
        hook = dhooks_lite.Webhook(
            url=self.url,
            user_agent=dhooks_lite.UserAgent(
                name=APP_NAME, url=HOMEPAGE_URL, version=__version__
            ),
        )
        response = hook.execute(
            content=message.get("content"),
            embeds=embeds,
            username=message.get("username"),
            avatar_url=message.get("avatar_url"),
            wait_for_response=True,
            max_retries=0,  # we will handle retries ourselves
        )
        logger.debug("headers: %s", response.headers)
        logger.debug("status_code: %s", response.status_code)
        logger.debug("content: %s", response.content)
        if response.status_code == self.HTTP_TOO_MANY_REQUESTS:
            logger.error(
                "%s: Received too many requests error from API: %s",
                self,
                response.content,
            )
            try:
                retry_after = int(response.headers["Retry-After"]) + 2
            except (ValueError, KeyError):
                retry_after = WebhookTooManyRequests.DEFAULT_RESET_AFTER
            cache.set(
                key=self._blocked_cache_key(), value="BLOCKED", timeout=retry_after
            )
            raise WebhookTooManyRequests(retry_after)
        return response

    def _blocked_cache_key(self) -> str:
        return f"{__title__}_webhook_{self.pk}_blocked"

    @staticmethod
    def create_message_link(name: str, url: str) -> str:
        """Create link for a Discord message"""
        if name and url:
            return f"[{str(name)}]({str(url)})"
        return str(name)
