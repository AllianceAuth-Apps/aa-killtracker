import dhooks_lite

from app_utils.testing import NoSocketsTestCase

from killtracker.core.trackers import (
    _create_embed,
    create_discord_message_from_killmail,
)
from killtracker.core.zkb import TrackerInfo, _EntityCount
from killtracker.models import Tracker
from killtracker.tests.testdata.factories import (
    EveEntityInventoryTypeFactory,
    KillmailAttackerFactory,
    KillmailFactory,
    KillmailVictimFactory,
    TrackerFactory,
)


class TestCreateEmbed(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        pass

    def test_should_create_normal_embed(self):
        # given
        tracker = TrackerFactory()
        km = KillmailFactory()
        # when
        embed = _create_embed(tracker, km)
        # then
        self.assertIsInstance(embed, dhooks_lite.Embed)

    def test_should_create_normal_for_killmail_without_value(self):
        # given
        tracker = TrackerFactory()
        km = KillmailFactory(zkb__total_value=None)
        # when
        embed = _create_embed(tracker, km)
        # then
        self.assertIsInstance(embed, dhooks_lite.Embed)

    def test_should_create_embed_without_victim_alliance(self):
        # given
        tracker = TrackerFactory()
        km = KillmailFactory(victim__alliance_id=None)
        # when
        embed = _create_embed(tracker, km)
        # then
        self.assertIsInstance(embed, dhooks_lite.Embed)

    def test_should_create_embed_without_victim_alliance_and_corporation(self):
        # given
        tracker = TrackerFactory()
        km = KillmailFactory(victim__alliance_id=None, victim__corporation_id=None)
        # when
        embed = _create_embed(tracker, km)
        # then
        self.assertIsInstance(embed, dhooks_lite.Embed)

    def test_should_create_embed_without_final_attacker(self):
        # given
        tracker = TrackerFactory()
        km = KillmailFactory()
        km.attackers.remove(km.attacker_final_blow())
        # when
        embed = _create_embed(tracker, km)
        # then
        self.assertIsInstance(embed, dhooks_lite.Embed)

    def test_should_create_embed_with_minimum_tracker_info(self):
        # given
        tracker = TrackerFactory()
        km = KillmailFactory().clone_with_tracker_info(tracker.pk)
        # when
        embed = _create_embed(tracker, km)
        # then
        self.assertIsInstance(embed, dhooks_lite.Embed)

    def test_should_create_embed_with_full_tracker_info(self):
        # given
        tracker = TrackerFactory()
        ship_type = EveEntityInventoryTypeFactory()
        km = KillmailFactory().clone_with_tracker_info(
            tracker.pk, jumps=3, distance=3.5, matching_ship_type_ids=[ship_type.id]
        )
        # when
        embed = _create_embed(tracker, km)
        # then
        self.assertIsInstance(embed, dhooks_lite.Embed)


class TestDiscordMessageFromKillmail(NoSocketsTestCase):
    def test_should_generate_without_tracker_info(self):
        # given
        tracker = TrackerFactory()
        km = KillmailFactory()

        # when
        message = create_discord_message_from_killmail(tracker, km)

        # then
        self.assertIsInstance(message.embeds[0], dhooks_lite.Embed)

    def test_can_add_intro_text(self):
        # given
        km = KillmailFactory()
        tracker = TrackerFactory(name="My Tracker")

        # when
        message = create_discord_message_from_killmail(tracker, km, intro_text="Alpha")

        # then
        self.assertIn("Alpha", message.content)

    def test_send_as_fleetkill(self):
        # given
        tracker = TrackerFactory(name="My Tracker", identify_fleets=True)
        km = KillmailFactory(
            attacker_count=10,
            tracker_info=TrackerInfo(
                tracker_pk=tracker.pk,
                main_org=_EntityCount(
                    id=42, name="Alpha", category=_EntityCount.CATEGORY_ALLIANCE
                ),
            ),
        )

        # when
        message = create_discord_message_from_killmail(tracker, km)

        # then
        self.assertIn("Fleetkill", message.embeds[0].title)

    def test_can_ping_everybody(self):
        # given
        tracker = TrackerFactory(ping_type=Tracker.ChannelPingType.EVERYBODY)
        km = KillmailFactory()

        # when
        message = create_discord_message_from_killmail(tracker, km)

        # then
        self.assertIn("@everybody", message.content)

    def test_can_ping_here(self):
        # given
        tracker = TrackerFactory(ping_type=Tracker.ChannelPingType.HERE)
        km = KillmailFactory()

        # when
        message = create_discord_message_from_killmail(tracker, km)

        # then
        self.assertIn("@here", message.content)

    def test_can_ping_nobody(self):
        # given
        tracker = TrackerFactory(ping_type=Tracker.ChannelPingType.NONE)
        km = KillmailFactory()

        # when
        message = create_discord_message_from_killmail(tracker, km)

        # then
        self.assertNotIn("@here", message.content)
        self.assertNotIn("@everybody", message.content)

    def test_can_disable_posting_tracker_name(self):
        # given
        tracker = TrackerFactory(is_posting_name=False)
        km = KillmailFactory()

        # when
        message = create_discord_message_from_killmail(tracker, km)

        # then
        self.assertNotIn(tracker.name, message.content)

    def test_can_generate_message_for_npc_killmail(self):
        # given
        tracker = TrackerFactory()
        km = KillmailFactory(is_npc=True)

        # when
        message = create_discord_message_from_killmail(tracker, km)

        # then
        self.assertIsInstance(message.embeds[0], dhooks_lite.Embed)

    def test_can_handle_victim_without_character(self):
        # given
        tracker = TrackerFactory()
        km = KillmailFactory(victim=KillmailVictimFactory(character_id=None))

        # when
        message = create_discord_message_from_killmail(tracker, km)

        # then
        self.assertIsInstance(message.embeds[0], dhooks_lite.Embed)

    def test_can_handle_victim_without_corporation(self):
        # given
        tracker = TrackerFactory()
        km = KillmailFactory(victim=KillmailVictimFactory(corporation_id=None))

        # when
        message = create_discord_message_from_killmail(tracker, km)

        # then
        self.assertIsInstance(message.embeds[0], dhooks_lite.Embed)

    def test_can_handle_final_attacker_with_no_character(self):
        # given
        tracker = TrackerFactory()
        km = KillmailFactory(
            attackers=[KillmailAttackerFactory(is_final_blow=True, character_id=None)]
        )

        # when
        message = create_discord_message_from_killmail(tracker, km)

        # then
        self.assertIsInstance(message.embeds[0], dhooks_lite.Embed)


# --
