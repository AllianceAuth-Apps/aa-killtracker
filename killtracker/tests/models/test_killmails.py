import datetime as dt
from unittest.mock import patch

from django.utils.timezone import now

from app_utils.testing import NoSocketsTestCase

from killtracker.models import EveKillmail, EveKillmailAttacker
from killtracker.tests.testdata.factories import (
    EveEntityAllianceFactory,
    EveEntityCharacterFactory,
    EveEntityCorporationFactory,
    EveEntityFactionFactory,
    EveEntityInventoryTypeFactory,
    EveEntitySolarSystemFactory,
    EveKillmailFactory,
    KillmailAttackerFactory,
    KillmailFactory,
    KillmailVictimFactory,
)


class TestEveKillmailManager(NoSocketsTestCase):
    def test_create_from_killmail(self):
        # given
        km = KillmailFactory(attacker_count=1)

        # when
        ek: EveKillmail
        ek = EveKillmail.objects.create_from_killmail(km)

        # then
        self.assertIsInstance(ek, EveKillmail)
        self.assertEqual(ek.id, km.id)
        self.assertEqual(ek.solar_system.id, km.solar_system_id)
        self.assertEqual(ek.time, km.time)

        self.assertEqual(ek.alliance.id, km.victim.alliance_id)
        self.assertEqual(ek.character.id, km.victim.character_id)
        self.assertEqual(ek.corporation.id, km.victim.corporation_id)
        self.assertEqual(ek.damage_taken, km.victim.damage_taken)
        self.assertEqual(ek.ship_type.id, km.victim.ship_type_id)

        attacker_ids = list(ek.attackers.values_list("pk", flat=True))
        self.assertEqual(len(attacker_ids), 1)

        km_attacker = km.attackers[0]
        attacker: EveKillmailAttacker
        attacker = ek.attackers.get(pk=attacker_ids[0])
        self.assertEqual(attacker.alliance.id, km_attacker.alliance_id)
        self.assertEqual(attacker.character.id, km_attacker.character_id)
        self.assertEqual(attacker.corporation.id, km_attacker.corporation_id)
        self.assertEqual(attacker.damage_done, km_attacker.damage_done)
        self.assertEqual(attacker.security_status, km_attacker.security_status)
        self.assertEqual(attacker.ship_type.id, km_attacker.ship_type_id)
        self.assertEqual(attacker.weapon_type.id, km_attacker.weapon_type_id)
        self.assertTrue(attacker.is_final_blow)

        self.assertEqual(ek.location_id, km.zkb.location_id)
        self.assertEqual(ek.fitted_value, km.zkb.fitted_value)
        self.assertEqual(ek.total_value, km.zkb.total_value)
        self.assertEqual(ek.zkb_points, km.zkb.points)
        self.assertEqual(ek.is_awox, km.zkb.is_awox)
        self.assertEqual(ek.is_npc, km.zkb.is_npc)
        self.assertEqual(ek.is_solo, km.zkb.is_solo)

    def test_update_or_create_from_killmail(self):
        # given
        ek = EveKillmailFactory()
        km = KillmailFactory(id=ek.id)

        # 2nd time will be updated
        ek, created = EveKillmail.objects.update_or_create_from_killmail(km)
        self.assertFalse(created)
        self.assertEqual(ek.solar_system_id, km.solar_system_id)

    @patch("killtracker.managers.KILLTRACKER_PURGE_KILLMAILS_AFTER_DAYS", 1)
    def test_delete_stale(self):
        # given
        ek1 = EveKillmailFactory()
        EveKillmailFactory(time=now() - dt.timedelta(days=1, seconds=1))

        # when
        _, details = EveKillmail.objects.delete_stale()

        # then
        self.assertEqual(details["killtracker.EveKillmail"], 1)
        self.assertEqual(EveKillmail.objects.count(), 1)
        self.assertTrue(EveKillmail.objects.filter(id=ek1.id).exists())

    @patch("killtracker.managers.KILLTRACKER_PURGE_KILLMAILS_AFTER_DAYS", 0)
    def test_dont_delete_stale_when_turned_off(self):
        # given
        ek1 = EveKillmailFactory()
        ek2 = EveKillmailFactory(time=now() - dt.timedelta(days=1, seconds=1))

        # when
        _, details = EveKillmail.objects.delete_stale()

        # then
        self.assertFalse(details)
        self.assertEqual(EveKillmail.objects.count(), 2)
        self.assertTrue(EveKillmail.objects.filter(id=ek1.id).exists())
        self.assertTrue(EveKillmail.objects.filter(id=ek2.id).exists())

    def test_should_not_load_entities_when_all_are_resolved(self):
        EveKillmailFactory()
        self.assertEqual(EveKillmail.objects.all().load_entities(), 0)


class TestEveKillmail(NoSocketsTestCase):
    def test_entity_ids(self):
        character_1001 = EveEntityCharacterFactory(id=1001)
        character_1002 = EveEntityCharacterFactory(id=1002)
        character_1003 = EveEntityCharacterFactory(id=1003)
        character_1011 = EveEntityCharacterFactory(id=1011)
        alliance_3001 = EveEntityAllianceFactory(id=3001)
        alliance_3011 = EveEntityAllianceFactory(id=3011)
        corporation_2001 = EveEntityCorporationFactory(id=2001)
        corporation_2011 = EveEntityCorporationFactory(id=2011)
        faction_1 = EveEntityFactionFactory(id=500001)
        faction_2 = EveEntityFactionFactory(id=500004)
        ship_type_1 = EveEntityInventoryTypeFactory(id=34562)
        ship_type_2 = EveEntityInventoryTypeFactory(id=3756)
        ship_type_3 = EveEntityInventoryTypeFactory(id=603)
        weapon_type_1 = EveEntityInventoryTypeFactory(id=2977)
        weapon_type_2 = EveEntityInventoryTypeFactory(id=2488)

        a1 = KillmailAttackerFactory(
            alliance_id=alliance_3001.id,
            character_id=character_1001.id,
            corporation_id=corporation_2001.id,
            faction_id=faction_1.id,
            ship_type_id=ship_type_1.id,
            weapon_type_id=weapon_type_1.id,
        )
        a2 = KillmailAttackerFactory(
            alliance_id=alliance_3001.id,
            character_id=character_1002.id,
            corporation_id=corporation_2001.id,
            faction_id=faction_1.id,
            ship_type_id=ship_type_2.id,
            weapon_type_id=weapon_type_2.id,
        )
        a3 = KillmailAttackerFactory(
            alliance_id=alliance_3001.id,
            character_id=character_1003.id,
            corporation_id=corporation_2001.id,
            faction_id=faction_1.id,
            ship_type_id=ship_type_2.id,
            weapon_type_id=weapon_type_2.id,
            is_final_blow=True,
        )
        killmail = KillmailFactory(
            id=10000001,
            attackers=[a1, a2, a3],
            solar_system_id=EveEntitySolarSystemFactory(id=30004984).id,
            victim=KillmailVictimFactory(
                alliance_id=alliance_3011.id,
                character_id=character_1011.id,
                corporation_id=corporation_2011.id,
                faction_id=faction_2.id,
                ship_type_id=ship_type_3.id,
            ),
        )
        ek = EveKillmail.objects.create_from_killmail(killmail)

        # when
        result = ek.entity_ids()

        # then
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
