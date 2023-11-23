from datetime import timedelta
from unittest.mock import patch

from django.utils.timezone import now
from eveuniverse.models import EveEntity

from app_utils.testing import NoSocketsTestCase

from killtracker.models import EveKillmail
from killtracker.tests.testdata.factories import (
    EveKillmailAttackerFactory,
    EveKillmailFactory,
)
from killtracker.tests.testdata.helpers import (
    LoadTestDataMixin,
    load_eve_entities,
    load_eve_killmails,
    load_killmail,
)
from killtracker.tests.testdata.load_eveuniverse import load_eveuniverse

MODELS_PATH = "killtracker.models.killmails"


class TestEveKillmailManager(LoadTestDataMixin, NoSocketsTestCase):
    def test_create_from_killmail(self):
        # given
        killmail = load_killmail(10000001)
        # when
        eve_killmail = EveKillmail.objects.create_from_killmail(killmail)
        # then
        self.assertIsInstance(eve_killmail, EveKillmail)
        self.assertEqual(eve_killmail.id, 10000001)
        self.assertEqual(eve_killmail.solar_system, EveEntity.objects.get(id=30004984))
        self.assertAlmostEqual(eve_killmail.time, now(), delta=timedelta(seconds=60))

        self.assertEqual(eve_killmail.alliance, EveEntity.objects.get(id=3011))
        self.assertEqual(eve_killmail.character, EveEntity.objects.get(id=1011))
        self.assertEqual(eve_killmail.corporation, EveEntity.objects.get(id=2011))
        self.assertEqual(eve_killmail.faction, EveEntity.objects.get(id=500004))
        self.assertEqual(eve_killmail.damage_taken, 434)
        self.assertEqual(eve_killmail.ship_type, EveEntity.objects.get(id=603))

        attacker_ids = list(eve_killmail.attackers.values_list("pk", flat=True))
        self.assertEqual(len(attacker_ids), 3)

        attacker = eve_killmail.attackers.get(pk=attacker_ids[0])
        self.assertEqual(attacker.alliance, EveEntity.objects.get(id=3001))
        self.assertEqual(attacker.character, EveEntity.objects.get(id=1001))
        self.assertEqual(attacker.corporation, EveEntity.objects.get(id=2001))
        self.assertEqual(attacker.faction, EveEntity.objects.get(id=500001))
        self.assertEqual(attacker.damage_done, 434)
        self.assertEqual(attacker.security_status, -10)
        self.assertEqual(attacker.ship_type, EveEntity.objects.get(id=34562))
        self.assertEqual(attacker.weapon_type, EveEntity.objects.get(id=2977))
        self.assertTrue(attacker.is_final_blow)

        attacker = eve_killmail.attackers.get(pk=attacker_ids[1])
        self.assertEqual(attacker.alliance, EveEntity.objects.get(id=3001))
        self.assertEqual(attacker.character, EveEntity.objects.get(id=1002))
        self.assertEqual(attacker.corporation, EveEntity.objects.get(id=2001))
        self.assertEqual(attacker.faction, EveEntity.objects.get(id=500001))
        self.assertEqual(attacker.damage_done, 50)
        self.assertEqual(attacker.security_status, -10)
        self.assertEqual(attacker.ship_type, EveEntity.objects.get(id=3756))
        self.assertEqual(attacker.weapon_type, EveEntity.objects.get(id=2488))
        self.assertFalse(attacker.is_final_blow)

        attacker = eve_killmail.attackers.get(pk=attacker_ids[2])
        self.assertEqual(attacker.alliance, EveEntity.objects.get(id=3001))
        self.assertEqual(attacker.character, EveEntity.objects.get(id=1003))
        self.assertEqual(attacker.corporation, EveEntity.objects.get(id=2001))
        self.assertEqual(attacker.faction, EveEntity.objects.get(id=500001))
        self.assertEqual(attacker.damage_done, 99)
        self.assertEqual(attacker.security_status, 5)
        self.assertEqual(attacker.ship_type, EveEntity.objects.get(id=3756))
        self.assertEqual(attacker.weapon_type, EveEntity.objects.get(id=2488))
        self.assertFalse(attacker.is_final_blow)

        self.assertEqual(eve_killmail.location_id, 50012306)
        self.assertEqual(eve_killmail.fitted_value, 10000)
        self.assertEqual(eve_killmail.total_value, 10000)
        self.assertEqual(eve_killmail.zkb_points, 1)
        self.assertFalse(eve_killmail.is_npc)
        self.assertFalse(eve_killmail.is_solo)
        self.assertFalse(eve_killmail.is_awox)

    def test_update_or_create_from_killmail(self):
        killmail = load_killmail(10000001)

        # first time will be created
        eve_killmail, created = EveKillmail.objects.update_or_create_from_killmail(
            killmail
        )
        self.assertTrue(created)
        self.assertEqual(eve_killmail.solar_system_id, 30004984)

        # update record
        eve_killmail.solar_system = EveEntity.objects.get(id=30045349)
        eve_killmail.save()
        eve_killmail.refresh_from_db()
        self.assertEqual(eve_killmail.solar_system_id, 30045349)

        # 2nd time will be updated
        eve_killmail, created = EveKillmail.objects.update_or_create_from_killmail(
            killmail
        )
        self.assertEqual(eve_killmail.id, 10000001)
        self.assertFalse(created)
        self.assertEqual(eve_killmail.solar_system_id, 30004984)

    @patch("killtracker.managers.KILLTRACKER_PURGE_KILLMAILS_AFTER_DAYS", 1)
    def test_delete_stale(self):
        load_eve_killmails([10000001, 10000002, 10000003])
        km = EveKillmail.objects.get(id=10000001)
        km.time = now() - timedelta(days=1, seconds=1)
        km.save()

        _, details = EveKillmail.objects.delete_stale()

        self.assertEqual(details["killtracker.EveKillmail"], 1)
        self.assertEqual(EveKillmail.objects.count(), 2)
        self.assertTrue(EveKillmail.objects.filter(id=10000002).exists())
        self.assertTrue(EveKillmail.objects.filter(id=10000003).exists())

    @patch("killtracker.managers.KILLTRACKER_PURGE_KILLMAILS_AFTER_DAYS", 0)
    def test_dont_delete_stale_when_turned_off(self):
        load_eve_killmails([10000001, 10000002, 10000003])
        km = EveKillmail.objects.get(id=10000001)
        km.time = now() - timedelta(days=1, seconds=1)
        km.save()

        self.assertIsNone(EveKillmail.objects.delete_stale())
        self.assertEqual(EveKillmail.objects.count(), 3)

    def test_load_entities(self):
        load_eve_killmails([10000001, 10000002])
        self.assertEqual(EveKillmail.objects.all().load_entities(), 0)


class TestEveKillmail(LoadTestDataMixin, NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        killmail = load_killmail(10000001)
        cls.eve_killmail = EveKillmail.objects.create_from_killmail(killmail)

    def test_str(self):
        self.assertEqual(str(self.eve_killmail), "ID:10000001")

    def test_repr(self):
        self.assertEqual(repr(self.eve_killmail), "EveKillmail(id=10000001)")

    def test_entity_ids(self):
        result = self.eve_killmail.entity_ids()
        expected = {
            1011,
            2011,
            3011,
            603,
            30004984,
            1001,
            1002,
            1003,
            2001,
            3001,
            34562,
            2977,
            3756,
            2488,
            500001,
            500004,
        }
        self.assertSetEqual(result, expected)


class TestEveKillmail2(NoSocketsTestCase):
    def test_should_create_eve_killmail(self):
        load_eveuniverse()
        load_eve_entities()
        # when
        obj = EveKillmailFactory()
        # then
        self.assertIsInstance(obj, EveKillmail)


class TestEveKillmailAttacker(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        load_eveuniverse()
        load_eve_entities()

    def test_str_returns_character(self):
        # given
        obj = EveKillmailAttackerFactory()
        # when
        result = str(obj)
        # then
        self.assertEqual(str(obj.character), result)

    def test_str_returns_corporation(self):
        # given
        obj = EveKillmailAttackerFactory(character=None)
        # when
        result = str(obj)
        # then
        self.assertEqual(str(obj.corporation), result)

    def test_str_returns_alliance(self):
        # given
        obj = EveKillmailAttackerFactory(character=None, corporation=None)
        # when
        result = str(obj)
        # then
        self.assertEqual(str(obj.alliance), result)
