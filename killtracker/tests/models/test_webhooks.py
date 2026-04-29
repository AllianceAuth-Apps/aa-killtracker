from django.core.cache import cache
from django.test import TestCase

from killtracker.core.discord import DiscordMessage
from killtracker.tests.testdata.factories import WebhookFactory


class TestWebhookQueue(TestCase):
    def setUp(self):
        cache.clear()

    def test_reset_failed_messages(self):
        webhook = WebhookFactory()
        message = "Test message"
        webhook._error_queue.enqueue(message)
        webhook._error_queue.enqueue(message)
        self.assertEqual(webhook._error_queue.size(), 2)
        self.assertEqual(webhook._main_queue.size(), 0)
        webhook.reset_failed_messages()
        self.assertEqual(webhook._error_queue.size(), 0)
        self.assertEqual(webhook._main_queue.size(), 2)

    def test_should_enqueue_and_dequeue_message_from_main_queue(self):
        webhook = WebhookFactory()
        m1 = DiscordMessage(content="content")
        webhook.enqueue_message(m1)
        m2 = webhook.dequeue_message()
        self.assertEqual(m1, m2)

    def test_should_enqueue_and_dequeue_message_from_error_queue(self):
        webhook = WebhookFactory()
        m1 = DiscordMessage(content="content")
        webhook.enqueue_message(m1, is_error=True)
        m2 = webhook.dequeue_message(is_error=True)
        self.assertEqual(m1, m2)

    def test_should_return_size_of_main_queue(self):
        webhook = WebhookFactory()
        m1 = DiscordMessage(content="content")
        webhook.enqueue_message(m1)
        self.assertEqual(webhook.messages_queued(), 1)

    def test_should_return_size_of_error_queue(self):
        webhook = WebhookFactory()
        m1 = DiscordMessage(content="content")
        webhook.enqueue_message(m1, is_error=True)
        self.assertEqual(webhook.messages_queued(is_error=True), 1)

    def test_should_clear_main_queue(self):
        webhook = WebhookFactory()
        m1 = DiscordMessage(content="content")
        webhook.enqueue_message(m1)
        self.assertEqual(webhook.messages_queued(), 1)
        webhook.delete_queued_messages()
        self.assertEqual(webhook.messages_queued(), 0)

    def test_should_clear_error_queue(self):
        webhook = WebhookFactory()
        m1 = DiscordMessage(content="content")
        webhook.enqueue_message(m1, is_error=True)
        self.assertEqual(webhook.messages_queued(is_error=True), 1)
        webhook.delete_queued_messages(is_error=True)
        self.assertEqual(webhook.messages_queued(is_error=True), 0)


# --
