import json
from unittest.mock import patch

import dhooks_lite
import requests_mock
from bs4 import BeautifulSoup
from markdown import markdown

from django.core.cache import cache
from django.test import TestCase
from eveuniverse.models import EveConstellation, EveRegion, EveSolarSystem, EveType

from app_utils.json import JSONDateTimeDecoder
from app_utils.testing import NoSocketsTestCase

from killtracker.core.killmails import Killmail
from killtracker.exceptions import WebhookTooManyRequests
from killtracker.models import Webhook

from ..testdata.factories import TrackerFactory
from ..testdata.helpers import LoadTestDataMixin, load_killmail

MODELS_PATH = "killtracker.models.trackers"


class TestWebhookQueue(LoadTestDataMixin, TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def setUp(self) -> None:
        self.webhook_1.main_queue.clear()
        self.webhook_1.error_queue.clear()

    def test_reset_failed_messages(self):
        message = "Test message"
        self.webhook_1.error_queue.enqueue(message)
        self.webhook_1.error_queue.enqueue(message)
        self.assertEqual(self.webhook_1.error_queue.size(), 2)
        self.assertEqual(self.webhook_1.main_queue.size(), 0)
        self.webhook_1.reset_failed_messages()
        self.assertEqual(self.webhook_1.error_queue.size(), 0)
        self.assertEqual(self.webhook_1.main_queue.size(), 2)

    def test_discord_message_asjson_normal(self):
        embed = dhooks_lite.Embed(description="my_description")
        result = Webhook._discord_message_asjson(
            content="my_content",
            username="my_username",
            avatar_url="my_avatar_url",
            embeds=[embed],
        )
        message_python = json.loads(result, cls=JSONDateTimeDecoder)
        expected = {
            "content": "my_content",
            "embeds": [{"description": "my_description", "type": "rich"}],
            "username": "my_username",
            "avatar_url": "my_avatar_url",
        }
        self.assertDictEqual(message_python, expected)

    def test_discord_message_asjson_empty(self):
        with self.assertRaises(ValueError):
            Webhook._discord_message_asjson("")


class TestHasLocalizationClause(LoadTestDataMixin, NoSocketsTestCase):
    def test_has_localization_filter_1(self):
        tracker = TrackerFactory.build(webhook=self.webhook_1, exclude_high_sec=True)
        self.assertTrue(tracker.has_localization_clause)

        tracker = TrackerFactory.build(webhook=self.webhook_1, exclude_low_sec=True)
        self.assertTrue(tracker.has_localization_clause)

        tracker = TrackerFactory.build(webhook=self.webhook_1, exclude_null_sec=True)
        self.assertTrue(tracker.has_localization_clause)

        tracker = TrackerFactory.build(webhook=self.webhook_1, exclude_w_space=True)
        self.assertTrue(tracker.has_localization_clause)

        tracker = TrackerFactory.build(webhook=self.webhook_1, require_max_distance=10)
        self.assertTrue(tracker.has_localization_clause)

        tracker = TrackerFactory.build(webhook=self.webhook_1, require_max_jumps=10)
        self.assertTrue(tracker.has_localization_clause)

    def test_has_no_matching_clause(self):
        tracker = TrackerFactory(webhook=self.webhook_1)
        self.assertFalse(tracker.has_localization_clause)

    def test_has_localization_filter_3(self):
        tracker = TrackerFactory(webhook=self.webhook_1)
        tracker.require_regions.add(EveRegion.objects.get(id=10000014))
        self.assertTrue(tracker.has_localization_clause)

    def test_has_localization_filter_4(self):
        tracker = TrackerFactory(webhook=self.webhook_1)
        tracker.require_constellations.add(EveConstellation.objects.get(id=20000169))
        self.assertTrue(tracker.has_localization_clause)

    def test_has_localization_filter_5(self):
        tracker = TrackerFactory(webhook=self.webhook_1)
        tracker.require_solar_systems.add(EveSolarSystem.objects.get(id=30001161))
        self.assertTrue(tracker.has_localization_clause)


class TestHasTypeClause(LoadTestDataMixin, NoSocketsTestCase):
    def test_has_no_matching_clause(self):
        tracker = TrackerFactory(webhook=self.webhook_1)
        self.assertFalse(tracker.has_type_clause)

    def test_has_require_attackers_ship_groups(self):
        tracker = TrackerFactory(webhook=self.webhook_1)
        tracker.require_attackers_ship_groups.add(self.type_svipul.eve_group)
        self.assertTrue(tracker.has_type_clause)

    def test_has_require_attackers_ship_types(self):
        tracker = TrackerFactory(webhook=self.webhook_1)
        tracker.require_attackers_ship_types.add(self.type_svipul)
        self.assertTrue(tracker.has_type_clause)

    def test_has_require_victim_ship_groups(self):
        tracker = TrackerFactory(webhook=self.webhook_1)
        tracker.require_victim_ship_groups.add(self.type_svipul.eve_group)
        self.assertTrue(tracker.has_type_clause)

    def test_has_require_victim_ship_types(self):
        tracker = TrackerFactory(webhook=self.webhook_1)
        tracker.require_victim_ship_types.add(self.type_svipul)
        self.assertTrue(tracker.has_type_clause)


class TestSaveMethod(LoadTestDataMixin, NoSocketsTestCase):
    def test_black_color_is_none(self):
        tracker = TrackerFactory(webhook=self.webhook_1, color="#000000")
        tracker.refresh_from_db()
        self.assertFalse(tracker.color)


@requests_mock.Mocker()
class TestWebhookSendMessage(LoadTestDataMixin, TestCase):
    def setUp(self) -> None:
        self.message = Webhook._discord_message_asjson(content="Test message")
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
        response = self.webhook_1.send_message_to_webhook(self.message)
        # then
        self.assertTrue(response.status_ok)
        self.assertTrue(requests_mocker.called)

    def test_when_send_not_ok_returns_false(self, requests_mocker):
        # given
        requests_mocker.register_uri("POST", self.webhook_1.url, status_code=404)
        # when
        response = self.webhook_1.send_message_to_webhook(self.message)
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
            self.webhook_1.send_message_to_webhook(self.message)
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
            self.webhook_1.send_message_to_webhook(self.message)
        except Exception as ex:
            self.assertIsInstance(ex, WebhookTooManyRequests)
            self.assertEqual(ex.retry_after, WebhookTooManyRequests.DEFAULT_RESET_AFTER)
        else:
            self.fail("Did not raise excepted exception")


@patch(MODELS_PATH + ".Webhook.enqueue_message")
class TestTrackerGenerateKillmailMessage(LoadTestDataMixin, TestCase):
    def setUp(self) -> None:
        self.tracker = TrackerFactory(name="My Tracker", webhook=self.webhook_1)

    def test_should_generate_message(self, mock_enqueue_message):
        # given
        self.tracker.origin_solar_system_id = 30003067
        self.tracker.save()
        svipul = EveType.objects.get(name="Svipul")
        self.tracker.require_attackers_ship_types.add(svipul)
        self.tracker.require_attackers_ship_types.add(
            EveType.objects.get(name="Gnosis")
        )
        killmail = load_killmail(10000101)
        killmail_json = Killmail.from_json(killmail.asjson())
        # when
        self.tracker.generate_killmail_message(killmail_json)
        # then
        _, kwargs = mock_enqueue_message.call_args
        content = kwargs["content"]
        self.assertIn("My Tracker", content)
        embed = kwargs["embeds"][0]
        self.assertEqual(embed.title, "Haras | Svipul | Killmail")
        self.assertEqual(embed.thumbnail.url, svipul.icon_url(size=128))
        html = markdown(embed.description)
        description = "".join(
            BeautifulSoup(html, features="html.parser").findAll(text=True)
        )
        lines = description.splitlines()
        self.assertEqual(
            (
                "Lex Luthor (LexCorp) lost their Svipul in Haras (The Bleak Lands) "
                "worth 10.00k ISK."
            ),
            lines[0],
        )
        self.assertEqual(
            "Final blow by Bruce Wayne (Wayne Technologies) in a Svipul.", lines[1]
        )
