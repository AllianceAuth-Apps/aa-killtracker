import datetime as dt
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils.timezone import now

from app_utils.testing import reset_celery_once_locks

from killtracker.core import zkb
from killtracker.core.discord import (
    DiscordMessage,
    HTTPError,
    WebhookRateLimitExhausted,
)
from killtracker.models import EveKillmail
from killtracker.tasks import (
    delete_stale_killmails,
    generate_killmail_message,
    run_killtracker,
    run_tracker,
    send_messages_to_webhook,
    store_killmail,
)

from .testdata.factories import TrackerFactory
from .testdata.helpers import LoadTestDataMixin, load_eve_killmails, load_killmail

MODULE_PATH = "killtracker.tasks"


class CeleryRequestStub(object):
    def __init__(self):
        self.retries = 0


class TestTrackerBase(LoadTestDataMixin, TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tracker_1 = TrackerFactory(
            exclude_high_sec=True,
            exclude_null_sec=True,
            exclude_w_space=True,
            webhook=cls.webhook_1,
        )
        cls.tracker_2 = TrackerFactory(
            exclude_low_sec=True,
            exclude_null_sec=True,
            exclude_w_space=True,
            webhook=cls.webhook_1,
        )


@patch("celery.app.task.Context.called_directly", False)  # make retry work with eager
@override_settings(CELERY_ALWAYS_EAGER=True)
@patch(MODULE_PATH + ".workers.is_shutting_down", spec=True)
@patch(MODULE_PATH + ".delete_stale_killmails", spec=True)
@patch(MODULE_PATH + ".store_killmail", spec=True)
@patch(MODULE_PATH + ".zkb.fetch_killmail_from_redisq")
@patch(MODULE_PATH + ".run_tracker", spec=True)
class TestRunKilltracker(TestTrackerBase):
    @staticmethod
    def my_fetch_from_zkb():
        for killmail_id in [10000001, 10000002, 10000003, None]:
            if killmail_id:
                yield load_killmail(killmail_id)
            else:
                yield None

    def setUp(self):
        reset_celery_once_locks("killtracker")
        self.webhook_1.delete_queued_messages()
        self.webhook_1.delete_queued_messages(is_error=True)

    @patch(MODULE_PATH + ".KILLTRACKER_STORING_KILLMAILS_ENABLED", False)
    def test_should_run_normally(
        self,
        mock_run_tracker,
        mock_fetch_killmail_from_zkb_redisq,
        mock_store_killmail,
        mock_delete_stale_killmails,
        mock_is_shutting_down,
    ):
        # given
        mock_is_shutting_down.return_value = False
        mock_fetch_killmail_from_zkb_redisq.side_effect = self.my_fetch_from_zkb()
        self.webhook_1._error_queue.enqueue(load_killmail(10000004).asjson())
        # when
        run_killtracker.delay()
        # then
        self.assertEqual(mock_run_tracker.delay.call_count, 6)
        self.assertEqual(mock_store_killmail.si.call_count, 0)
        self.assertFalse(mock_delete_stale_killmails.delay.called)
        self.assertEqual(self.webhook_1._main_queue.size(), 1)
        self.assertEqual(self.webhook_1._error_queue.size(), 0)

    @patch(MODULE_PATH + ".KILLTRACKER_MAX_KILLMAILS_PER_RUN", 2)
    def test_should_stop_when_max_killmails_received(
        self,
        mock_run_tracker,
        mock_fetch_killmail_from_zkb_redisq,
        mock_store_killmail,
        mock_delete_stale_killmails,
        mock_is_shutting_down,
    ):
        # given
        mock_is_shutting_down.return_value = False
        mock_fetch_killmail_from_zkb_redisq.side_effect = self.my_fetch_from_zkb()
        # when
        run_killtracker.delay()
        # then
        self.assertEqual(mock_run_tracker.delay.call_count, 4)

    @patch(MODULE_PATH + ".KILLTRACKER_PURGE_KILLMAILS_AFTER_DAYS", 30)
    @patch(MODULE_PATH + ".KILLTRACKER_STORING_KILLMAILS_ENABLED", True)
    def test_can_store_killmails(
        self,
        mock_run_tracker,
        mock_fetch_killmail_from_zkb_redisq,
        mock_store_killmail,
        mock_delete_stale_killmails,
        mock_is_shutting_down,
    ):
        # given
        mock_is_shutting_down.return_value = False
        mock_fetch_killmail_from_zkb_redisq.side_effect = self.my_fetch_from_zkb()
        # when
        run_killtracker.delay()
        # then
        self.assertEqual(mock_run_tracker.delay.call_count, 6)
        self.assertEqual(mock_store_killmail.si.call_count, 3)
        self.assertTrue(mock_delete_stale_killmails.delay.called)

    @patch(MODULE_PATH + ".KILLTRACKER_MAX_KILLMAILS_PER_RUN", 2)
    def test_should_retry_when_too_many_errors_received(
        self,
        mock_run_tracker,
        mock_fetch_killmail_from_zkb_redisq,
        mock_store_killmail,
        mock_delete_stale_killmails,
        mock_is_shutting_down,
    ):
        # given
        mock_is_shutting_down.return_value = False
        mock_fetch_killmail_from_zkb_redisq.side_effect = zkb.ZKBTooManyRequestsError(
            now() + dt.timedelta(minutes=1)
        )
        # when/then
        run_killtracker.delay()
        # then
        self.assertEqual(mock_run_tracker.delay.call_count, 0)

    @patch(MODULE_PATH + ".KILLTRACKER_STORING_KILLMAILS_ENABLED", False)
    def test_should_abort_when_worker_is_offline(
        self,
        mock_run_tracker,
        mock_fetch_killmail_from_zkb_redisq,
        mock_store_killmail,
        mock_delete_stale_killmails,
        mock_is_shutting_down,
    ):
        # given
        mock_is_shutting_down.return_value = True
        mock_fetch_killmail_from_zkb_redisq.side_effect = self.my_fetch_from_zkb()
        # when
        run_killtracker.delay()
        # then
        self.assertEqual(mock_run_tracker.delay.call_count, 0)
        self.assertEqual(mock_store_killmail.si.call_count, 0)
        self.assertFalse(mock_delete_stale_killmails.delay.called)


@patch(MODULE_PATH + ".send_messages_to_webhook", spec=True)
@patch(MODULE_PATH + ".generate_killmail_message", spec=True)
class TestRunTracker(TestTrackerBase):
    def setUp(self) -> None:
        zkb.Killmail.delete_all()

    def test_should_generate_message_when_killmail_matches(
        self, mock_enqueue_killmail_message, mock_send_messages_to_webhook
    ):
        # given
        km = load_killmail(10000001)
        km.save()
        # when
        run_tracker(self.tracker_1.pk, km.id)
        # then
        self.assertTrue(mock_enqueue_killmail_message.delay.called)
        self.assertFalse(mock_send_messages_to_webhook.delay.called)

    def test_should_do_nothing_when_killmail_does_not_match(
        self, mock_enqueue_killmail_message, mock_send_messages_to_webhook
    ):
        # given
        km = load_killmail(10000003)
        km.save()
        # when
        run_tracker(self.tracker_1.pk, km.id)
        # then
        self.assertFalse(mock_enqueue_killmail_message.delay.called)
        self.assertFalse(mock_send_messages_to_webhook.delay.called)

    def test_should_start_message_sending_when_queue_non_empty(
        self, mock_enqueue_killmail_message, mock_send_messages_to_webhook
    ):
        # given
        km = load_killmail(10000003)
        km.save()
        self.webhook_1.enqueue_message(DiscordMessage(content="test"))
        # when
        run_tracker(self.tracker_1.pk, km.id)
        # then
        self.assertFalse(mock_enqueue_killmail_message.delay.called)
        self.assertTrue(mock_send_messages_to_webhook.delay.called)

    def test_should_do_nothing_when_killmail_not_found(
        self, mock_enqueue_killmail_message, mock_send_messages_to_webhook
    ):
        # when
        run_tracker(self.tracker_1.pk, 666)
        # then
        self.assertFalse(mock_enqueue_killmail_message.delay.called)
        self.assertFalse(mock_send_messages_to_webhook.delay.called)


@patch(MODULE_PATH + ".generate_killmail_message.retry", spec=True)
@patch(MODULE_PATH + ".send_messages_to_webhook", spec=True)
class TestGenerateKillmailMessage(TestTrackerBase):
    def setUp(self) -> None:
        zkb.Killmail.delete_all()
        self.webhook_1.delete_queued_messages()
        self.webhook_1.delete_queued_messages(is_error=True)
        self.retries = 0
        km = load_killmail(10000001)
        km.save()
        self.killmail_id = km.id

    def my_retry(self, *args, **kwargs):
        self.retries += 1
        if self.retries > kwargs["max_retries"]:
            raise kwargs["exc"]
        generate_killmail_message(self.tracker_1.pk, self.killmail_id)

    def test_should_generate_message_and_start_sending(
        self, mock_send_messages_to_webhook, mock_retry
    ):
        # given
        mock_retry.side_effect = self.my_retry
        # when
        generate_killmail_message(self.tracker_1.pk, self.killmail_id)
        # then
        self.assertTrue(mock_send_messages_to_webhook.delay.called)
        self.assertEqual(self.webhook_1._main_queue.size(), 1)
        self.assertFalse(mock_retry.called)

    def test_should_abort_when_killmail_not_found(
        self, mock_send_messages_to_webhook, mock_retry
    ):
        # given
        mock_retry.side_effect = self.my_retry
        # when
        generate_killmail_message(self.tracker_1.pk, 999)
        # then
        self.assertFalse(mock_send_messages_to_webhook.delay.called)
        self.assertEqual(self.webhook_1._main_queue.size(), 0)
        self.assertFalse(mock_retry.called)

    @patch(MODULE_PATH + ".KILLTRACKER_GENERATE_MESSAGE_MAX_RETRIES", 3)
    @patch(MODULE_PATH + ".Tracker.generate_killmail_message", spec=True)
    def test_should_retry_when_generating_message_fails(
        self, mock_generate_killmail_message, mock_send_messages_to_webhook, mock_retry
    ):
        # given
        mock_retry.side_effect = self.my_retry
        mock_generate_killmail_message.side_effect = RuntimeError
        # when/then
        with self.assertRaises(RuntimeError):
            generate_killmail_message(self.tracker_1.pk, self.killmail_id)
        self.assertFalse(mock_send_messages_to_webhook.delay.called)
        self.assertEqual(self.webhook_1._main_queue.size(), 0)
        self.assertEqual(mock_retry.call_count, 4)


@patch("celery.app.task.Context.called_directly", False)  # make retry work with eager
@override_settings(CELERY_ALWAYS_EAGER=True)
@patch(MODULE_PATH + ".workers.is_shutting_down", spec=True)
@patch(MODULE_PATH + ".Webhook.send_message", spec=True)
class TestSendMessagesToWebhook(TestTrackerBase):
    def setUp(self) -> None:
        reset_celery_once_locks("killtracker")
        self.webhook_1._main_queue.clear()
        self.webhook_1._error_queue.clear()

    def test_should_send_one_message(self, mock_send_message, mock_is_shutting_down):
        # given
        mock_is_shutting_down.return_value = False
        mock_send_message.return_value = 42
        self.webhook_1.enqueue_message(DiscordMessage(content="Test message"))
        # when
        send_messages_to_webhook.delay(self.webhook_1.pk)
        # then
        self.assertEqual(mock_send_message.call_count, 1)

    def test_should_send_three_messages(self, mock_send_message, mock_is_shutting_down):
        # given
        mock_is_shutting_down.return_value = False
        mock_send_message.return_value = [1, 2, 3]
        self.webhook_1.enqueue_message(DiscordMessage(content="Test message"))
        self.webhook_1.enqueue_message(DiscordMessage(content="Test message"))
        self.webhook_1.enqueue_message(DiscordMessage(content="Test message"))
        # when
        send_messages_to_webhook.delay(self.webhook_1.pk)
        # then
        self.assertEqual(mock_send_message.call_count, 3)

    def test_should_do_nothing_when_queue_is_empty(
        self, mock_send_message, mock_is_shutting_down
    ):
        # given
        mock_is_shutting_down.return_value = False
        # when
        send_messages_to_webhook.delay(self.webhook_1.pk)
        # then
        self.assertEqual(mock_send_message.call_count, 0)

    def test_should_put_failed_message_in_error_queue(
        self, mock_send_message, mock_is_shutting_down
    ):
        # given
        mock_is_shutting_down.return_value = False
        mock_send_message.side_effect = HTTPError(404)
        self.webhook_1.enqueue_message(DiscordMessage(content="Test message"))
        # when
        send_messages_to_webhook.delay(self.webhook_1.pk)
        # then
        self.assertEqual(mock_send_message.call_count, 1)
        self.assertEqual(self.webhook_1._main_queue.size(), 0)
        self.assertEqual(self.webhook_1._error_queue.size(), 1)

    def test_should_retry_on_too_many_requests_error(
        self, mock_send_message, mock_is_shutting_down
    ):
        # given
        mock_is_shutting_down.return_value = False
        mock_send_message.side_effect = [WebhookRateLimitExhausted(10), lambda: None]
        self.webhook_1.enqueue_message(DiscordMessage(content="Test message"))
        # when
        send_messages_to_webhook.delay(self.webhook_1.pk)
        # then
        self.assertEqual(mock_send_message.call_count, 2)

    def test_should_abort_when_worker_is_shutting_down(
        self, mock_send_message, mock_is_shutting_down
    ):
        # given
        mock_is_shutting_down.return_value = True
        mock_send_message.return_value = 42
        self.webhook_1.enqueue_message(DiscordMessage(content="Test message"))
        # when
        send_messages_to_webhook(self.webhook_1.pk)
        # then
        self.assertEqual(mock_send_message.call_count, 0)

    @patch(MODULE_PATH + ".KILLTRACKER_MAX_MESSAGES_SENT_PER_RUN", 1)
    def test_retry_when_limit_is_reached(
        self, mock_send_message, mock_is_shutting_down
    ):
        # given
        mock_is_shutting_down.return_value = False
        mock_send_message.return_value = [1, 2]
        self.webhook_1.enqueue_message(DiscordMessage(content="Test message"))
        self.webhook_1.enqueue_message(DiscordMessage(content="Test message"))
        # when
        send_messages_to_webhook.delay(self.webhook_1.pk)
        # then
        self.assertEqual(mock_send_message.call_count, 2)


@patch(MODULE_PATH + ".logger", spec=True)
class TestStoreKillmail(TestTrackerBase):
    def setUp(self) -> None:
        zkb.Killmail.delete_all()

    def test_should_save_killmail_to_database(self, mock_logger):
        # given
        km = load_killmail(10000001)
        km.save()
        # when
        store_killmail(km.id)
        # then
        self.assertTrue(EveKillmail.objects.filter(id=10000001).exists())
        self.assertFalse(mock_logger.warning.called)

    def test_should_abort_when_killmail_not_found_in_storage(self, mock_logger):
        # when
        store_killmail(666)
        # then
        self.assertFalse(EveKillmail.objects.filter(id=10000001).exists())
        self.assertTrue(mock_logger.error.called)

    def test_should_generate_warning_when_killmail_exists(self, mock_logger):
        # given
        load_eve_killmails([10000001])
        km = load_killmail(10000001)
        km.save()
        # when
        store_killmail(km.id)
        # then
        self.assertTrue(mock_logger.warning.called)


@patch(MODULE_PATH + ".EveKillmail.objects.delete_stale")
class TestDeleteStaleKillmails(TestTrackerBase):
    def test_normal(self, mock_delete_stale):
        mock_delete_stale.return_value = (1, {"killtracker.EveKillmail": 1})
        delete_stale_killmails()
        self.assertTrue(mock_delete_stale.called)
