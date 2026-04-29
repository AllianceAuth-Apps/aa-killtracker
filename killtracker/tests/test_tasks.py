import datetime as dt
from unittest.mock import patch

from celery.exceptions import Retry

from django.core.cache import cache
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils.timezone import now

from app_utils.testing import reset_celery_once_locks

from killtracker import tasks
from killtracker.core import zkb
from killtracker.core.discord import (
    DiscordMessage,
    HTTPError,
    WebhookRateLimitExhausted,
)
from killtracker.models import EveKillmail

from .testdata.factories import (
    EveEntitySolarSystemFactory,
    EveKillmailFactory,
    KillmailFactory,
    TrackerFactory,
    WebhookFactory,
)

MODULE_PATH = "killtracker.tasks"

# def my_fetch_from_zkb():
#     for killmail_id in [10000001, 10000002, 10000003, None]:
#         if killmail_id:
#             yield load_killmail(killmail_id)
#         else:
#             yield None


@patch("celery.app.task.Context.called_directly", False)  # make retry work with eager
@override_settings(CELERY_ALWAYS_EAGER=True)
@patch(MODULE_PATH + ".workers.is_shutting_down", spec=True)
@patch(MODULE_PATH + ".zkb.fetch_killmail_from_r2z2")
@patch(MODULE_PATH + ".run_tracker", spec=True)
class TestRunKilltracker(TestCase):
    def setUp(self):
        reset_celery_once_locks("killtracker")

    @patch(MODULE_PATH + ".KILLTRACKER_STORING_KILLMAILS_ENABLED", False)
    def test_should_run_normally(
        self,
        mock_run_tracker,
        mock_fetch_killmail_from_r2z2,
        mock_is_shutting_down,
    ):
        # given
        mock_is_shutting_down.return_value = False
        mock_fetch_killmail_from_r2z2.side_effect = [
            KillmailFactory(),
            KillmailFactory(),
            None,
        ]
        TrackerFactory()

        # when
        tasks.run_killtracker.delay()

        # then
        self.assertEqual(mock_run_tracker.delay.call_count, 2)

    @patch(MODULE_PATH + ".KILLTRACKER_PURGE_KILLMAILS_AFTER_DAYS", 30)
    @patch(MODULE_PATH + ".KILLTRACKER_STORING_KILLMAILS_ENABLED", True)
    def test_can_store_killmails(
        self,
        mock_run_tracker,
        mock_fetch_killmail_from_r2z2,
        mock_is_shutting_down,
    ):
        # given
        mock_is_shutting_down.return_value = False
        km = KillmailFactory()
        mock_fetch_killmail_from_r2z2.side_effect = [km, None]

        # when
        tasks.run_killtracker.delay()

        # then
        EveKillmail.objects.filter(id=km.id).exists()

    @patch(MODULE_PATH + ".KILLTRACKER_MAX_KILLMAILS_PER_RUN", 2)
    def test_should_retry_when_too_many_errors_received(
        self,
        mock_run_tracker,
        mock_fetch_killmail_from_r2z2,
        mock_is_shutting_down,
    ):
        # given
        mock_is_shutting_down.return_value = False
        mock_fetch_killmail_from_r2z2.side_effect = zkb.R2Z2TooManyRequestsError(
            now() + dt.timedelta(minutes=1)
        )
        # when/then
        with self.assertRaises(Retry):
            tasks.run_killtracker()

    @patch(MODULE_PATH + ".KILLTRACKER_STORING_KILLMAILS_ENABLED", False)
    def test_should_abort_when_worker_is_offline(
        self,
        mock_run_tracker,
        mock_fetch_killmail_from_r2z2,
        mock_is_shutting_down,
    ):
        # given
        mock_is_shutting_down.return_value = True
        mock_fetch_killmail_from_r2z2.side_effect = [KillmailFactory(), None]

        # when
        tasks.run_killtracker.delay()

        # then
        self.assertEqual(mock_run_tracker.delay.call_count, 0)


@patch(MODULE_PATH + ".send_messages_to_webhook", spec=True)
@patch(MODULE_PATH + ".generate_killmail_message", spec=True)
class TestRunTracker(TestCase):
    def setUp(self) -> None:
        cache.clear()

    def test_should_generate_message_when_killmail_matches(
        self, mock_enqueue_killmail_message, mock_send_messages_to_webhook
    ):
        # given
        tracker = TrackerFactory()
        km = KillmailFactory()
        km.save()

        # when
        tasks.run_tracker(tracker.pk, km.id)

        # then
        self.assertTrue(mock_enqueue_killmail_message.delay.called)
        self.assertFalse(mock_send_messages_to_webhook.delay.called)

    def test_should_do_nothing_when_killmail_does_not_match(
        self, mock_enqueue_killmail_message, mock_send_messages_to_webhook
    ):
        # given
        tracker = TrackerFactory(require_min_attackers=3)
        km = KillmailFactory(attacker_count=1)
        km.save()

        # when
        tasks.run_tracker(tracker.pk, km.id)

        # then
        self.assertFalse(mock_enqueue_killmail_message.delay.called)
        self.assertFalse(mock_send_messages_to_webhook.delay.called)

    def test_should_start_message_sending_when_not_matching_and_queue_non_empty(
        self, mock_enqueue_killmail_message, mock_send_messages_to_webhook
    ):
        # given
        tracker = TrackerFactory(require_min_attackers=3)
        km = KillmailFactory(attacker_count=1)
        km.save()
        tracker.webhook.enqueue_message(DiscordMessage(content="test"))

        # when
        tasks.run_tracker(tracker.pk, km.id)

        # then
        self.assertFalse(mock_enqueue_killmail_message.delay.called)
        self.assertTrue(mock_send_messages_to_webhook.delay.called)

    def test_should_do_nothing_when_killmail_not_found(
        self, mock_enqueue_killmail_message, mock_send_messages_to_webhook
    ):
        # given
        tracker = TrackerFactory()

        # when

        tasks.run_tracker(tracker.pk, 666)

        # then
        self.assertFalse(mock_enqueue_killmail_message.delay.called)
        self.assertFalse(mock_send_messages_to_webhook.delay.called)


@patch("celery.app.task.Context.called_directly", False)  # make retry work with eager
@override_settings(CELERY_ALWAYS_EAGER=True)
@patch(MODULE_PATH + ".Webhook.send_message", spec=True)
class TestGenerateKillmailMessage(TestCase):
    def setUp(self) -> None:
        zkb.Killmail.delete_all()

    def test_should_generate_message_and_start_sending(self, mock_send_message):
        # given
        tracker = TrackerFactory()
        km = KillmailFactory()
        km.save()

        # when
        got = tasks.generate_killmail_message(tracker.pk, km.id)

        # then
        self.assertTrue(got)
        self.assertTrue(mock_send_message.called)

    def test_should_abort_when_killmail_not_found(self, mock_send_message):
        # given
        tracker = TrackerFactory()

        # when
        got = tasks.generate_killmail_message(tracker.pk, 999)

        # then
        self.assertFalse(got)
        self.assertFalse(mock_send_message.called)

    @patch(MODULE_PATH + ".KILLTRACKER_GENERATE_MESSAGE_MAX_RETRIES", 3)
    @patch(MODULE_PATH + ".Tracker.generate_killmail_message", spec=True)
    def test_should_retry_when_generating_message_fails(
        self, mock_generate_killmail_message, mock_send_message
    ):
        # given
        mock_generate_killmail_message.side_effect = RuntimeError
        tracker = TrackerFactory()
        km = KillmailFactory()
        km.save()

        # when
        with self.assertRaises(Retry):
            tasks.generate_killmail_message(tracker.pk, km.id)


@patch("celery.app.task.Context.called_directly", False)  # make retry work with eager
@override_settings(CELERY_ALWAYS_EAGER=True)
@patch(MODULE_PATH + ".workers.is_shutting_down", spec=True)
@patch(MODULE_PATH + ".Webhook.send_message", spec=True)
class TestSendMessagesToWebhook(TestCase):
    def setUp(self) -> None:
        cache.clear()

    def test_should_send_one_message(self, mock_send_message, mock_is_shutting_down):
        # given
        mock_is_shutting_down.return_value = False
        mock_send_message.return_value = 42
        webhook = WebhookFactory()
        webhook.enqueue_message(DiscordMessage(content="Test message"))

        # when
        tasks.send_messages_to_webhook.delay(webhook.pk)

        # then
        self.assertEqual(mock_send_message.call_count, 1)

    def test_should_send_three_messages(self, mock_send_message, mock_is_shutting_down):
        # given
        mock_is_shutting_down.return_value = False
        mock_send_message.return_value = [1, 2, 3]
        webhook = WebhookFactory()
        webhook.enqueue_message(DiscordMessage(content="Test message"))
        webhook.enqueue_message(DiscordMessage(content="Test message"))
        webhook.enqueue_message(DiscordMessage(content="Test message"))
        # when

        tasks.send_messages_to_webhook.delay(webhook.pk)
        # then
        self.assertEqual(mock_send_message.call_count, 3)

    def test_should_do_nothing_when_queue_is_empty(
        self, mock_send_message, mock_is_shutting_down
    ):
        # given
        mock_is_shutting_down.return_value = False
        webhook = WebhookFactory()

        # when
        tasks.send_messages_to_webhook.delay(webhook.pk)

        # then
        self.assertEqual(mock_send_message.call_count, 0)

    def test_should_put_failed_message_in_error_queue(
        self, mock_send_message, mock_is_shutting_down
    ):
        # given
        mock_is_shutting_down.return_value = False
        mock_send_message.side_effect = HTTPError(404)
        webhook = WebhookFactory()
        webhook.enqueue_message(DiscordMessage(content="Test message"))

        # when
        tasks.send_messages_to_webhook.delay(webhook.pk)

        # then
        self.assertEqual(mock_send_message.call_count, 1)
        self.assertEqual(webhook._main_queue.size(), 0)
        self.assertEqual(webhook._error_queue.size(), 1)

    def test_should_retry_on_too_many_requests_error(
        self, mock_send_message, mock_is_shutting_down
    ):
        # given
        mock_is_shutting_down.return_value = False
        mock_send_message.side_effect = [WebhookRateLimitExhausted(10), lambda: None]
        webhook = WebhookFactory()
        webhook.enqueue_message(DiscordMessage(content="Test message"))

        # when
        tasks.send_messages_to_webhook.delay(webhook.pk)

        # then
        self.assertEqual(mock_send_message.call_count, 2)

    def test_should_abort_when_worker_is_shutting_down(
        self, mock_send_message, mock_is_shutting_down
    ):
        # given
        mock_is_shutting_down.return_value = True
        mock_send_message.return_value = 42
        webhook = WebhookFactory()
        webhook.enqueue_message(DiscordMessage(content="Test message"))

        # when
        tasks.send_messages_to_webhook(webhook.pk)

        # then
        self.assertEqual(mock_send_message.call_count, 0)

    @patch(MODULE_PATH + ".KILLTRACKER_MAX_MESSAGES_SENT_PER_RUN", 1)
    def test_retry_when_limit_is_reached(
        self, mock_send_message, mock_is_shutting_down
    ):
        # given
        mock_is_shutting_down.return_value = False
        mock_send_message.return_value = [1, 2]
        webhook = WebhookFactory()
        webhook.enqueue_message(DiscordMessage(content="Test message"))
        webhook.enqueue_message(DiscordMessage(content="Test message"))

        # when
        tasks.send_messages_to_webhook.delay(webhook.pk)

        # then
        self.assertEqual(mock_send_message.call_count, 2)


class TestStoreKillmail(TransactionTestCase):
    def setUp(self) -> None:
        zkb.Killmail.delete_all()

    def test_should_save_all_killmail_to_the_database(self):
        # given
        km = KillmailFactory()
        km.save()

        # when
        got = tasks.store_killmail(km.id)

        # then
        self.assertTrue(got)
        self.assertTrue(EveKillmail.objects.filter(id=km.id).exists())

    def test_should_abort_when_killmail_not_found_in_storage(self):
        # when
        got = tasks.store_killmail(666)

        # then
        self.assertFalse(got)
        self.assertFalse(EveKillmail.objects.filter(id=10000001).exists())

    def test_should_overwrite_existing_killmails_in_database(self):
        # given
        km = EveKillmailFactory()
        solar_system = EveEntitySolarSystemFactory()
        KillmailFactory(id=km.id, solar_system_id=solar_system.id).save()

        # when
        got = tasks.store_killmail(km.id)

        # then
        self.assertFalse(got)
        km.refresh_from_db()
        self.assertNotEqual(km.solar_system, solar_system)


@patch("killtracker.managers.KILLTRACKER_PURGE_KILLMAILS_AFTER_DAYS", 1)
@override_settings(CELERY_ALWAYS_EAGER=True, CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestDeleteStaleKillmails(TestCase):
    def test_can_delete_stale_killmail(self):
        # given
        ek1 = EveKillmailFactory()
        EveKillmailFactory(time=now() - dt.timedelta(days=1, seconds=1))

        # when
        tasks.delete_stale_killmails()

        # then
        self.assertEqual(EveKillmail.objects.count(), 1)
        self.assertTrue(EveKillmail.objects.filter(id=ek1.id).exists())
