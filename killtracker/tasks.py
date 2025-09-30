"""Tasks for killtracker."""

import time

from celery import Task, chain, shared_task

from django.db import IntegrityError
from django.utils.timezone import now
from eveuniverse.core.esitools import is_esi_online
from eveuniverse.tasks import update_unresolved_eve_entities

from allianceauth.services.hooks import get_extension_logger
from allianceauth.services.tasks import QueueOnce
from app_utils.esi import retry_task_if_esi_is_down
from app_utils.logging import LoggerAddTag

from killtracker import __title__
from killtracker.app_settings import (
    KILLTRACKER_DISCORD_SEND_DELAY,
    KILLTRACKER_GENERATE_MESSAGE_MAX_RETRIES,
    KILLTRACKER_GENERATE_MESSAGE_RETRY_COUNTDOWN,
    KILLTRACKER_MAX_KILLMAILS_PER_RUN,
    KILLTRACKER_MAX_MESSAGES_SENT_PER_RUN,
    KILLTRACKER_PURGE_KILLMAILS_AFTER_DAYS,
    KILLTRACKER_RUN_TIMEOUT,
    KILLTRACKER_STORING_KILLMAILS_ENABLED,
    KILLTRACKER_TASK_OBJECTS_CACHE_TIMEOUT,
    KILLTRACKER_TASKS_TIMEOUT,
)
from killtracker.core import workers
from killtracker.core.discord import (
    DiscordMessage,
    HTTPError,
    WebhookRateLimitExhausted,
)
from killtracker.core.zkb import Killmail, KillmailDoesNotExist, ZKBTooManyRequestsError
from killtracker.models import EveKillmail, Tracker, Webhook

logger = LoggerAddTag(get_extension_logger(__name__), __title__)


@shared_task(bind=True, base=QueueOnce, timeout=KILLTRACKER_TASKS_TIMEOUT)
def run_killtracker(self: Task) -> int:
    """Fetches and processes new killmails from ZKB API
    and returns how many killmails were processed.

    This is the main periodic task for running Killtracker.
    """
    if not is_esi_online():
        logger.warning("ESI is currently offline. Aborting")
        return 0

    for webhook in Webhook.objects.filter(is_enabled=True):
        webhook.reset_failed_messages()

    started = time.time()

    def is_timed_out() -> bool:
        elapsed = time.time() - started
        return KILLTRACKER_RUN_TIMEOUT - elapsed <= 0

    killmails_count = 0
    for _ in range(KILLTRACKER_MAX_KILLMAILS_PER_RUN):
        if is_timed_out():
            break

        if workers.is_shutting_down(self):
            logger.debug("Aborting due to worker shutdown")
            break

        killmail = None
        try:
            killmail = Killmail.create_from_zkb_redisq()
        except ZKBTooManyRequestsError as ex:
            seconds = (ex.retry_at - now()).total_seconds()
            if seconds < 0:
                break

            logger.warning(
                "Killtracker has been baned from ZKB API for %f seconds", seconds
            )
            raise self.retry(countdown=seconds)

        if not killmail:
            break

        killmails_count += 1
        killmail.save()
        for tracker in Tracker.objects.filter(is_enabled=True):
            run_tracker.delay(tracker_pk=tracker.pk, killmail_id=killmail.id)

        if KILLTRACKER_STORING_KILLMAILS_ENABLED:
            chain(
                store_killmail.si(killmail.id),
                update_unresolved_eve_entities.si(),
            ).delay()

    elapsed = time.time() - started
    logger.info(
        "Killtracker processed %d new killmails from ZKB in %f seconds",
        killmails_count,
        elapsed,
    )

    if (
        KILLTRACKER_STORING_KILLMAILS_ENABLED
        and KILLTRACKER_PURGE_KILLMAILS_AFTER_DAYS > 0
    ):
        delete_stale_killmails.delay()

    return killmails_count


@shared_task(bind=True, max_retries=None)
def run_tracker(
    self: Task, tracker_pk: int, killmail_id: int, ignore_max_age: bool = False
) -> None:
    """Run tracker for given killmail and trigger sending if needed."""
    retry_task_if_esi_is_down(self)
    tracker: Tracker = Tracker.objects.get_cached(
        pk=tracker_pk,
        select_related="webhook",
        timeout=KILLTRACKER_TASK_OBJECTS_CACHE_TIMEOUT,
    )
    try:
        killmail = Killmail.get(killmail_id)
    except KillmailDoesNotExist as ex:
        logger.error("Aborting. %s", ex)
        return

    killmail_new = tracker.process_killmail(
        killmail=killmail, ignore_max_age=ignore_max_age
    )
    if killmail_new:
        logger.info("%s: Killmail %d matches", tracker, killmail_id)
        killmail_new.save()
        generate_killmail_message.delay(tracker_pk=tracker_pk, killmail_id=killmail_id)
    elif tracker.webhook.messages_queued():
        send_messages_to_webhook.delay(webhook_pk=tracker.webhook.pk)


@shared_task(bind=True, max_retries=None)
def generate_killmail_message(self: Task, tracker_pk: int, killmail_id: int) -> None:
    """Generate and enqueue message from given killmail and start sending."""
    retry_task_if_esi_is_down(self)
    tracker: Tracker = Tracker.objects.get_cached(
        pk=tracker_pk,
        select_related="webhook",
        timeout=KILLTRACKER_TASK_OBJECTS_CACHE_TIMEOUT,
    )
    try:
        killmail = Killmail.get(killmail_id)
    except KillmailDoesNotExist as ex:
        logger.error("Aborting. %s", ex)
        return
    try:
        tracker.generate_killmail_message(killmail)
    except Exception as ex:
        will_retry = self.request.retries < KILLTRACKER_GENERATE_MESSAGE_MAX_RETRIES
        logger.warning(
            "%s: Failed to generate killmail %s.%s",
            tracker,
            killmail.id,
            " Will retry." if will_retry else "",
            exc_info=True,
        )
        raise self.retry(
            max_retries=KILLTRACKER_GENERATE_MESSAGE_MAX_RETRIES,
            countdown=KILLTRACKER_GENERATE_MESSAGE_RETRY_COUNTDOWN,
            exc=ex,
        )

    send_messages_to_webhook.delay(webhook_pk=tracker.webhook.pk)
    logger.info(
        "%s: Added message from killmail %s to send queue", tracker, killmail.id
    )


@shared_task(timeout=KILLTRACKER_TASKS_TIMEOUT)
def store_killmail(killmail_id: int) -> None:
    """Stores killmail as EveKillmail object."""
    try:
        killmail = Killmail.get(killmail_id)
    except KillmailDoesNotExist as ex:
        logger.error("Aborting. %s", ex)
        return
    try:
        EveKillmail.objects.create_from_killmail(killmail, resolve_ids=False)
    except IntegrityError:
        logger.warning(
            "%s: Failed to store killmail, because it already exists", killmail.id
        )
    else:
        logger.info("%s: Stored killmail", killmail.id)


@shared_task(timeout=KILLTRACKER_TASKS_TIMEOUT)
def delete_stale_killmails() -> None:
    """Deletes all EveKillmail objects that are considered stale."""
    _, details = EveKillmail.objects.delete_stale()
    if details:
        logger.info("Deleted %d stale killmails", details["killtracker.EveKillmail"])


@shared_task(
    bind=True, base=QueueOnce, timeout=KILLTRACKER_TASKS_TIMEOUT, max_retries=None
)
def send_messages_to_webhook(self: Task, webhook_pk: int) -> None:
    """Sends queued messages to a webhook.

    Note: This task will retry after processing a set number of messages
    to avoid running potentially forever.
    """

    webhook: Webhook = Webhook.objects.get(pk=webhook_pk)
    if not webhook.is_enabled:
        logger.info("%s: Webhook is disabled - aborting", webhook)
        return

    for _ in range(KILLTRACKER_MAX_MESSAGES_SENT_PER_RUN):
        if workers.is_shutting_down(self):
            logger.debug("Aborting due to worker shutdown")
            return

        message = webhook.dequeue_message()
        if not message:
            logger.debug("%s: No more messages to send for webhook", webhook)
            break

        try:
            message_id = webhook.send_message(message)

        except WebhookRateLimitExhausted as ex:
            webhook.enqueue_message(message)
            logger.warning(
                "%s: Webhook temporarily blocked. Retrying at %s.", webhook, ex.retry_at
            )
            raise self.retry(eta=ex.retry_at)

        except HTTPError as ex:
            webhook.enqueue_message(message, is_error=True)
            logger.warning(
                "%s: Failed to send message for Killmail %d to webhook, will retry. "
                "HTTP status code: %d",
                webhook,
                message.killmail_id,
                ex.status_code,
            )
            continue

        logger.info(
            "%s: Discord message %s created for killmail %d",
            webhook,
            message_id,
            message.killmail_id,
        )

    if webhook.messages_queued() > 0:
        raise self.retry(countdown=KILLTRACKER_DISCORD_SEND_DELAY)


@shared_task(timeout=KILLTRACKER_TASKS_TIMEOUT)
def send_test_message_to_webhook(webhook_pk: int, count: int = 1) -> None:
    """Send a test message to given webhook.

    Optional inform user about result if user ok is given.
    """
    try:
        webhook = Webhook.objects.get(pk=webhook_pk)
    except Webhook.DoesNotExist:
        logger.error("Webhook with pk = %s does not exist", webhook_pk)
        return

    for num in range(count):
        num_str = f"{num+1}/{count} " if count > 1 else ""
        message = DiscordMessage(content=f"Test message {num_str}from {__title__}.")
        webhook.enqueue_message(message)

    send_messages_to_webhook.delay(webhook.pk)
    logger.info("%s test messages submitted to webhook %s", count, webhook)
