"""Webhooks models for killtracker."""

from typing import Optional

from simple_mq import SimpleMQ

from django.db import models
from django.utils.translation import gettext_lazy as _

from allianceauth.services.hooks import get_extension_logger
from app_utils.allianceauth import get_redis_client
from app_utils.logging import LoggerAddTag
from app_utils.urls import static_file_absolute_url

from killtracker import __title__
from killtracker.app_settings import KILLTRACKER_WEBHOOK_SET_AVATAR
from killtracker.core.discord import DiscordMessage, send_message_to_webhook
from killtracker.managers import WebhookManager

logger = LoggerAddTag(get_extension_logger(__name__), __title__)


class Webhook(models.Model):
    """A webhook to receive messages"""

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
        self._main_queue = self._create_queue("main")
        self._error_queue = self._create_queue("error")

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
        del state["_main_queue"]
        del state["_error_queue"]
        return state

    def __setstate__(self, state):
        # Restore instance attributes (i.e., filename and lineno).
        self.__dict__.update(state)
        # Restore the previously opened file's state. To do so, we need to
        # reopen it and read from it until the line count is restored.
        self._main_queue = self._create_queue("main")
        self._error_queue = self._create_queue("error")

    def save(self, *args, **kwargs):
        is_new = self.id is None  # type: ignore
        super().save(*args, **kwargs)
        if is_new:
            self._main_queue = self._create_queue("main")
            self._error_queue = self._create_queue("error")

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
        if self._error_queue and self._main_queue:
            while True:
                message = self._error_queue.dequeue()
                if message is None:
                    break

                self._main_queue.enqueue(message)
                counter += 1

        return counter

    def enqueue_message(self, message: DiscordMessage, is_error: bool = False) -> int:
        """Enqueues a discord message to be send with this webhook.

        Returns the updated number of messages in the main queue.
        """
        q = self._error_queue if is_error else self._main_queue

        if not q:
            return 0

        if KILLTRACKER_WEBHOOK_SET_AVATAR:
            message.username = __title__

        if KILLTRACKER_WEBHOOK_SET_AVATAR:
            brand_url = static_file_absolute_url("killtracker/killtracker_logo.png")
            message.avatar_url = brand_url

        return q.enqueue(message.to_json())

    def dequeue_message(self, is_error: bool = False) -> Optional[DiscordMessage]:
        """Dequeues a message from the main queue and return it.

        Returns None if the queue is empty.
        """
        q = self._error_queue if is_error else self._main_queue
        s = q.dequeue()
        if not s:
            return None

        return DiscordMessage.from_json(s)

    def messages_queued(self, is_error: bool = False) -> int:
        """Returns how many message are currently in the queue."""
        q = self._error_queue if is_error else self._main_queue
        if not q:
            return 0

        return q.size()

    def delete_queued_messages(self, is_error: bool = False) -> int:
        """Deletes all messages in a queue and returns how many messages where deleted."""
        q = self._error_queue if is_error else self._main_queue
        if not q:
            return 0

        return q.clear()

    def send_message(self, message: DiscordMessage) -> int:
        """Send a message to the webhook."""
        return send_message_to_webhook(name=self.name, url=self.url, message=message)

    @staticmethod
    def create_message_link(name: str, url: str) -> str:
        """Create link for a Discord message"""
        if name and url:
            return f"[{str(name)}]({str(url)})"
        return str(name)
