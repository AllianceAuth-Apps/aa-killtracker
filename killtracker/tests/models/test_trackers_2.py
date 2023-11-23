from unittest.mock import patch

from bs4 import BeautifulSoup
from markdown import markdown

from django.test import TestCase
from eveuniverse.models import EveConstellation, EveRegion, EveSolarSystem, EveType

from app_utils.testing import NoSocketsTestCase

from killtracker.core.killmails import Killmail
from killtracker.tests.testdata.factories import TrackerFactory
from killtracker.tests.testdata.helpers import LoadTestDataMixin, load_killmail

MODELS_PATH = "killtracker.models.trackers"


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
