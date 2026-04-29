import datetime as dt
from unittest.mock import patch

import dhooks_lite
import pook

from django.test import TestCase
from django.utils.timezone import now

from app_utils.testing import CacheFake, NoSocketsTestCase

from killtracker.core.discord import (
    DiscordMessage,
    HTTPError,
    WebhookRateLimitExhausted,
    _make_key_last_request,
    _make_key_retry_at,
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


@patch(MODULE_PATH + ".cache", new_callable=CacheFake)
class TestWebhookSendMessage(TestCase):
    def setUp(self) -> None:
        self.name = "webhook"
        self.message = DiscordMessage(content="Test message")
        self.url = "https://webhook.example.com/1234"
        self.message_api = {
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
        }

    @pook.on
    def test_when_send_ok_returns_true(self, _mock_cache: CacheFake):
        # given
        pook.post(self.url, reply=200, response_json=self.message_api)

        # when
        got = send_message_to_webhook(
            name=self.name, url=self.url, message=self.message
        )

        # then
        self.assertTrue(pook.isdone())
        self.assertEqual(got, 223704706495545344)

    @pook.on
    def test_should_ignore_invalid_key_for_last_request(self, mock_cache: CacheFake):
        # given
        mock_cache.set(_make_key_last_request(self.url), "invalid")
        pook.post(self.url, reply=200, response_json=self.message_api)

        # when
        got = send_message_to_webhook(
            name=self.name, url=self.url, message=self.message
        )

        # then
        self.assertTrue(pook.isdone())
        self.assertEqual(got, 223704706495545344)

    @pook.on
    def test_should_ignore_invalid_key_for_retry_at(self, mock_cache: CacheFake):
        # given
        mock_cache.set(_make_key_retry_at(self.url), "invalid")
        pook.post(self.url, reply=200, response_json=self.message_api)

        # when
        got = send_message_to_webhook(
            name=self.name, url=self.url, message=self.message
        )

        # then
        self.assertTrue(pook.isdone())
        self.assertEqual(got, 223704706495545344)

    @pook.on
    def test_when_send_not_ok_raise_error(self, mock_cache: CacheFake):
        # given
        pook.post(self.url, reply=404)

        # when
        with self.assertRaises(HTTPError) as ctx:
            send_message_to_webhook(name=self.name, url=self.url, message=self.message)

        # then
        self.assertTrue(pook.isdone())
        self.assertEqual(ctx.exception.status_code, 404)

    @pook.on
    def test_raise_too_many_requests_when_received_from_api(
        self, _mock_cache: CacheFake
    ):
        # given
        pook.post(
            self.url,
            reply=429,
            response_json={
                "global": False,
                "message": "You are being rate limited.",
                "retry_after": 2000,
            },
            response_headers={
                "x-ratelimit-remaining": "5",
                "x-ratelimit-reset-after": "60",
                "Retry-After": "2000",
            },
        )

        # when/then
        with self.assertRaises(WebhookRateLimitExhausted) as ctx:
            send_message_to_webhook(name=self.name, url=self.url, message=self.message)

        self.assertTrue(pook.isdone())
        self.assertTrue(ctx.exception.retry_at)

    @pook.on
    def test_too_many_requests_no_retry_value(self, mock_cache: CacheFake):
        # given
        pook.post(
            self.url,
            reply=429,
            response_headers={
                "x-ratelimit-remaining": "5",
                "x-ratelimit-reset-after": "60",
            },
        )

        # when/then
        with self.assertRaises(WebhookRateLimitExhausted) as ctx:
            send_message_to_webhook(name=self.name, url=self.url, message=self.message)

        self.assertTrue(pook.isdone())
        self.assertTrue(ctx.exception.retry_at)

    @pook.on
    def test_should_reraise_exception_when_not_expired(self, mock_cache: CacheFake):
        # given
        key = _make_key_retry_at(self.url)
        mock_cache.set(key, now() + dt.timedelta(hours=1))

        # when
        with self.assertRaises(WebhookRateLimitExhausted) as ctx:
            send_message_to_webhook(name=self.name, url=self.url, message=self.message)

        # then
        self.assertTrue(ctx.exception.retry_at)
