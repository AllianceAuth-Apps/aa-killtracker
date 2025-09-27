import requests_mock

from django.core.cache import cache
from django.test import TestCase

from killtracker.core.discord_messages import DiscordMessage
from killtracker.exceptions import WebhookTooManyRequests
from killtracker.models import Webhook
from killtracker.tests.testdata.helpers import LoadTestDataMixin


class TestWebhookQueue(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.webhook_1 = Webhook.objects.create(
            name="Webhook 1", url="http://www.example.com/webhook_1", is_enabled=True
        )

    def setUp(self) -> None:
        self.webhook_1._main_queue.clear()
        self.webhook_1._error_queue.clear()

    def test_reset_failed_messages(self):
        message = "Test message"
        self.webhook_1._error_queue.enqueue(message)
        self.webhook_1._error_queue.enqueue(message)
        self.assertEqual(self.webhook_1._error_queue.size(), 2)
        self.assertEqual(self.webhook_1._main_queue.size(), 0)
        self.webhook_1.reset_failed_messages()
        self.assertEqual(self.webhook_1._error_queue.size(), 0)
        self.assertEqual(self.webhook_1._main_queue.size(), 2)

    def test_should_enqueue_and_dequeue_message_from_main_queue(self):
        m1 = DiscordMessage(content="content")
        self.webhook_1.enqueue_message(m1)
        m2 = self.webhook_1.dequeue_message()
        self.assertEqual(m1, m2)

    def test_should_enqueue_and_dequeue_message_from_error_queue(self):
        m1 = DiscordMessage(content="content")
        self.webhook_1.enqueue_message(m1, is_error=True)
        m2 = self.webhook_1.dequeue_message(is_error=True)
        self.assertEqual(m1, m2)

    def test_should_return_size_of_main_queue(self):
        m1 = DiscordMessage(content="content")
        self.webhook_1.enqueue_message(m1)
        self.assertEqual(self.webhook_1.messages_queued(), 1)

    def test_should_return_size_of_error_queue(self):
        m1 = DiscordMessage(content="content")
        self.webhook_1.enqueue_message(m1, is_error=True)
        self.assertEqual(self.webhook_1.messages_queued(is_error=True), 1)

    def test_should_clear_main_queue(self):
        m1 = DiscordMessage(content="content")
        self.webhook_1.enqueue_message(m1)
        self.assertEqual(self.webhook_1.messages_queued(), 1)
        self.webhook_1.delete_queued_messages()
        self.assertEqual(self.webhook_1.messages_queued(), 0)

    def test_should_clear_error_queue(self):
        m1 = DiscordMessage(content="content")
        self.webhook_1.enqueue_message(m1, is_error=True)
        self.assertEqual(self.webhook_1.messages_queued(is_error=True), 1)
        self.webhook_1.delete_queued_messages(is_error=True)
        self.assertEqual(self.webhook_1.messages_queued(is_error=True), 0)


@requests_mock.Mocker()
class TestWebhookSendMessage(LoadTestDataMixin, TestCase):
    def setUp(self) -> None:
        self.message = DiscordMessage(content="Test message")
        cache.clear()

    def test_when_send_ok_returns_true(self, requests_mocker):
        # given
        requests_mocker.register_uri(
            "POST",
            self.webhook_1.url,
            status_code=200,
            json={
                "name": "test webhook",
                "type": 1,
                "channel_id": "199737254929760256",
                "token": "3d89bb7572e0fb30d8128367b3b1b44fecd1726de135cbe28a41f8b2f777c372ba2939e72279b94526ff5d1bd4358d65cf11",
                "avatar": None,
                "guild_id": "199737254929760256",
                "id": "223704706495545344",
                "application_id": None,
                "user": {
                    "username": "test",
                    "discriminator": "7479",
                    "id": "190320984123768832",
                    "avatar": "b004ec1740a63ca06ae2e14c5cee11f3",
                    "public_flags": 131328,
                },
            },
        )
        # when
        response = self.webhook_1.send_message(self.message)
        # then
        self.assertTrue(response.status_ok)
        self.assertTrue(requests_mocker.called)

    def test_when_send_not_ok_returns_false(self, requests_mocker):
        # given
        requests_mocker.register_uri("POST", self.webhook_1.url, status_code=404)
        # when
        response = self.webhook_1.send_message(self.message)
        # then
        self.assertFalse(response.status_ok)
        self.assertTrue(requests_mocker.called)

    def test_too_many_requests_normal(self, requests_mocker):
        # given
        requests_mocker.register_uri(
            "POST",
            self.webhook_1.url,
            status_code=429,
            json={
                "global": False,
                "message": "You are being rate limited.",
                "retry_after": 2000,
            },
            headers={
                "x-ratelimit-remaining": "5",
                "x-ratelimit-reset-after": "60",
                "Retry-After": "2000",
            },
        )
        # when/then
        try:
            self.webhook_1.send_message(self.message)
        except Exception as ex:
            self.assertIsInstance(ex, WebhookTooManyRequests)
            self.assertEqual(ex.retry_after, 2002)
        else:
            self.fail("Did not raise excepted exception")

        self.assertAlmostEqual(
            cache.ttl(self.webhook_1._blocked_cache_key()), 2002, delta=5
        )

    def test_too_many_requests_no_retry_value(self, requests_mocker):
        # given
        requests_mocker.register_uri(
            "POST",
            self.webhook_1.url,
            status_code=429,
            headers={
                "x-ratelimit-remaining": "5",
                "x-ratelimit-reset-after": "60",
            },
        )
        # when/then
        try:
            self.webhook_1.send_message(self.message)
        except Exception as ex:
            self.assertIsInstance(ex, WebhookTooManyRequests)
            self.assertEqual(ex.retry_after, WebhookTooManyRequests.DEFAULT_RESET_AFTER)
        else:
            self.fail("Did not raise excepted exception")
