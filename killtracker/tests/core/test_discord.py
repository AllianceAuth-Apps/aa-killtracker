from unittest.mock import patch

import dhooks_lite
import requests_mock

from app_utils.testing import NoSocketsTestCase

from killtracker.core.discord import (
    DiscordMessage,
    HTTPError,
    WebhookTooManyRequests,
    send_message_to_webhook,
)

MODULE_PATH = "killtracker.core.discord"


class TestDiscordMessage(NoSocketsTestCase):
    def test_can_create(self):
        o = DiscordMessage(content="content")
        self.assertEqual(o.content, "content")

    def test_should_raise_exception_when_invalid(self):
        with self.assertRaises(ValueError):
            DiscordMessage(username="user")

    def test_can_convert_to_and_from_json_1(self):
        o1 = DiscordMessage(
            content="content",
        )
        s = o1.to_json()
        o2 = DiscordMessage.from_json(s)
        self.assertEqual(o1, o2)

    def test_can_convert_to_and_from_json_2(self):
        o1 = DiscordMessage(
            avatar_url="avatar_url",
            content="content",
            embeds=[dhooks_lite.Embed(description="description")],
            killmail_id=42,
            username="username",
        )
        s = o1.to_json()
        o2 = DiscordMessage.from_json(s)
        self.assertEqual(o1, o2)


@requests_mock.Mocker()
@patch(MODULE_PATH + ".cache_get_timestamp")
class TestWebhookSendMessage(NoSocketsTestCase):
    def setUp(self) -> None:
        self.name = "webhook"
        self.message = DiscordMessage(content="Test message")
        self.url = "https://webhook.example.com/1234"

    def test_when_send_ok_returns_true(self, requests_mocker, mock_cache_get):
        # given
        mock_cache_get.return_value = None
        requests_mocker.register_uri(
            "POST",
            self.url,
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
        got = send_message_to_webhook(
            name=self.name, url=self.url, message=self.message
        )
        # then
        self.assertEqual(got, 223704706495545344)
        self.assertTrue(requests_mocker.called)

    def test_when_send_not_ok_raise_error(self, requests_mocker, mock_cache_get):
        # given
        mock_cache_get.return_value = None
        requests_mocker.register_uri("POST", self.url, status_code=404)
        # when
        with self.assertRaises(HTTPError) as ctx:
            send_message_to_webhook(name=self.name, url=self.url, message=self.message)
        # then
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertTrue(requests_mocker.called)

    def test_too_many_requests_normal(self, requests_mocker, mock_cache_get):
        # given
        mock_cache_get.return_value = None
        requests_mocker.register_uri(
            "POST",
            self.url,
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
        with self.assertRaises(WebhookTooManyRequests) as ctx:
            send_message_to_webhook(name=self.name, url=self.url, message=self.message)

        self.assertTrue(ctx.exception.retry_at)

    def test_too_many_requests_no_retry_value(self, requests_mocker, mock_cache_get):
        # given
        mock_cache_get.return_value = None
        requests_mocker.register_uri(
            "POST",
            self.url,
            status_code=429,
            headers={
                "x-ratelimit-remaining": "5",
                "x-ratelimit-reset-after": "60",
            },
        )
        # when/then
        with self.assertRaises(WebhookTooManyRequests) as ctx:
            send_message_to_webhook(name=self.name, url=self.url, message=self.message)

        self.assertTrue(ctx.exception.retry_at)
