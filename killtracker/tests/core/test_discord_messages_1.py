import dhooks_lite

from app_utils.testing import NoSocketsTestCase

from killtracker.core import discord_messages

from ..testdata.factories import KillmailFactory, TrackerFactory
from ..testdata.helpers import load_eve_entities
from ..testdata.load_eveuniverse import load_eveuniverse


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
        embed = discord_messages.create_embed(tracker, killmail)
        # then
        self.assertIsInstance(embed, dhooks_lite.Embed)

    def test_should_create_normal_for_killmail_without_value(self):
        # given
        tracker = TrackerFactory()
        killmail = KillmailFactory(zkb__total_value=None)
        # when
        embed = discord_messages.create_embed(tracker, killmail)
        # then
        self.assertIsInstance(embed, dhooks_lite.Embed)

    def test_should_create_embed_without_victim_character(self):
        # given
        tracker = TrackerFactory()
        killmail = KillmailFactory(victim__character_id=None)
        # when
        embed = discord_messages.create_embed(tracker, killmail)
        # then
        self.assertIsInstance(embed, dhooks_lite.Embed)
