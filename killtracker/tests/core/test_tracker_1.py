import dhooks_lite

from app_utils.testing import NoSocketsTestCase

from killtracker.core.trackers import (
    _create_embed,
    create_discord_message_from_killmail,
)
from killtracker.tests.testdata.factories import (
    EveEntityVariant,
    KillmailFactory,
    TrackerFactory,
    random_eve_entity,
)
from killtracker.tests.testdata.helpers import load_eve_entities
from killtracker.tests.testdata.load_eveuniverse import load_eveuniverse


class TestCreateEmbed(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        load_eveuniverse()
        load_eve_entities()

    def test_should_create_normal_embed(self):
        # given
        tracker = TrackerFactory()
        killmail = KillmailFactory()
        # when
        embed = _create_embed(tracker, killmail)
        # then
        self.assertIsInstance(embed, dhooks_lite.Embed)

    def test_should_create_normal_for_killmail_without_value(self):
        # given
        tracker = TrackerFactory()
        killmail = KillmailFactory(zkb__total_value=None)
        # when
        embed = _create_embed(tracker, killmail)
        # then
        self.assertIsInstance(embed, dhooks_lite.Embed)

    def test_should_create_embed_without_victim_alliance(self):
        # given
        tracker = TrackerFactory()
        killmail = KillmailFactory(victim__alliance_id=None)
        # when
        embed = _create_embed(tracker, killmail)
        # then
        self.assertIsInstance(embed, dhooks_lite.Embed)

    def test_should_create_embed_without_victim_alliance_and_corporation(self):
        # given
        tracker = TrackerFactory()
        killmail = KillmailFactory(
            victim__alliance_id=None, victim__corporation_id=None
        )
        # when
        embed = _create_embed(tracker, killmail)
        # then
        self.assertIsInstance(embed, dhooks_lite.Embed)

    def test_should_create_embed_without_final_attacker(self):
        # given
        tracker = TrackerFactory()
        killmail = KillmailFactory()
        killmail.attackers.remove(killmail.attacker_final_blow())
        # when
        embed = _create_embed(tracker, killmail)
        # then
        self.assertIsInstance(embed, dhooks_lite.Embed)

    def test_should_create_embed_with_minimum_tracker_info(self):
        # given
        tracker = TrackerFactory()
        killmail = KillmailFactory().clone_with_tracker_info(tracker.pk)
        # when
        embed = _create_embed(tracker, killmail)
        # then
        self.assertIsInstance(embed, dhooks_lite.Embed)

    def test_should_create_embed_with_full_tracker_info(self):
        # given
        tracker = TrackerFactory()
        ship_type = random_eve_entity(EveEntityVariant.SHIP_TYPE)
        killmail = KillmailFactory().clone_with_tracker_info(
            tracker.pk, jumps=3, distance=3.5, matching_ship_type_ids=[ship_type.id]
        )
        # when
        embed = _create_embed(tracker, killmail)
        # then
        self.assertIsInstance(embed, dhooks_lite.Embed)


class TestDiscordMessageFromKillmail(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        load_eveuniverse()
        load_eve_entities()

    def test_should_create_from_killmail(self):
        # given
        tracker = TrackerFactory()
        killmail = KillmailFactory()
        # when
        m = create_discord_message_from_killmail(tracker, killmail)
        # then
        self.assertIsInstance(m.embeds[0], dhooks_lite.Embed)
