from django.test import TestCase

from killtracker.core.discord import DiscordMessage
from killtracker.models import Webhook


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
