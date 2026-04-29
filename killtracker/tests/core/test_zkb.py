import datetime as dt
import fnmatch
import unittest
from unittest.mock import patch

import pook
import requests

from django.core.cache import cache
from django.test import TestCase
from django.utils.timezone import now

from app_utils.testing import CacheFake, NoSocketsTestCase

from killtracker.core import zkb
from killtracker.core.zkb import (
    _ZKB_API_URL,
    Killmail,
    KillmailDoesNotExist,
    _EntityCount,
    fetch_killmail_from_api,
)
from killtracker.tests import CacheStub
from killtracker.tests.testdata.factories import (
    EveEntityAllianceFactory,
    EveEntityCharacterFactory,
    EveEntityCorporationFactory,
    EveEntityFactionFactory,
    EveEntityInventoryTypeFactory,
    EveEntitySolarSystemFactory,
    KillmailAttackerFactory,
    KillmailFactory,
    KillmailVictimFactory,
    R2Z2ResponseFactory,
    TrackerFactory,
)

MODULE_PATH = "killtracker.core.zkb"
unittest.util._MAX_LENGTH = 1000


class CacheFake2(CacheFake):
    def delete_pattern(self, pattern: str, itersize=None) -> None:
        keys = []
        for k in self._cache:
            if fnmatch.fnmatch(k, pattern):
                keys.append(k)
        for k in keys:
            self.delete(k)
        return len(keys)


@patch(MODULE_PATH + ".cache", new_callable=CacheFake)
class TestFetchKillmailFromR2Z2(TestCase):
    @pook.on
    def test_should_return_killmail_from_scratch(self, mock_cache: CacheFake):
        # given
        sequence_id = 12345
        pook.get(
            "https://r2z2.zkillboard.com/ephemeral/sequence.json",
            reply=200,
            response_json={"sequence": sequence_id},
        )
        km_1 = KillmailFactory()
        pook.get(
            f"https://r2z2.zkillboard.com/ephemeral/{sequence_id}.json",
            reply=200,
            response_json=R2Z2ResponseFactory(killmail=km_1, sequence_id=sequence_id),
        )

        # when
        km_2 = zkb.fetch_killmail_from_r2z2()

        # then
        self.assertEqual(km_2.attackers, km_1.attackers)
        self.assertEqual(km_2.position, km_1.position)
        self.assertEqual(km_2.solar_system_id, km_1.solar_system_id)
        self.assertEqual(km_2.time, km_1.time)
        self.assertEqual(km_2.victim, km_1.victim)
        self.assertEqual(km_2.zkb, km_1.zkb)
        self.assertEqual(km_2, km_1)

    @pook.on
    def test_should_return_next_killmail(self, mock_cache: CacheFake):
        # given
        sequence_id = 12345
        mock_cache.set(zkb._KEY_LAST_SEQUENCE, sequence_id)
        km_1 = KillmailFactory()
        pook.get(
            f"https://r2z2.zkillboard.com/ephemeral/{sequence_id}.json",
            reply=200,
            response_json=R2Z2ResponseFactory(killmail=km_1, sequence_id=sequence_id),
        )

        # when
        km_2 = zkb.fetch_killmail_from_r2z2()

        # then
        self.assertEqual(km_2.id, km_1.id)

    @pook.on
    def test_should_return_none_when_api_returns_404(self, mock_cache: CacheFake):
        # given
        sequence_id = 12345
        mock_cache.set(zkb._KEY_LAST_SEQUENCE, sequence_id)
        pook.get(
            f"https://r2z2.zkillboard.com/ephemeral/{sequence_id}.json",
            reply=404,
            response_json={},
        )

        # when
        killmail = zkb.fetch_killmail_from_r2z2()

        # then
        self.assertIsNone(killmail)

    @pook.on
    def test_should_ignore_invalid_value_for_retry_at_key(self, mock_cache: CacheFake):
        # given
        mock_cache.set(zkb._KEY_RETRY_AT, "abc")
        mock_cache.set(zkb._KEY_LAST_SEQUENCE, 12345)
        pook.get(
            "https://r2z2.zkillboard.com/ephemeral/12345.json",
            reply=404,
            response_json={},
        )
        # when
        killmail = zkb.fetch_killmail_from_r2z2()
        # then
        self.assertIsNone(killmail)

    @pook.on
    def test_should_ignore_invalid_value_for_last_request_key(
        self, mock_cache: CacheFake
    ):
        # given
        mock_cache.set(zkb._KEY_LAST_REQUEST, "abc")
        mock_cache.set(zkb._KEY_LAST_SEQUENCE, 12345)
        pook.get(
            "https://r2z2.zkillboard.com/ephemeral/12345.json",
            reply=404,
            response_json={},
        )
        # when
        killmail = zkb.fetch_killmail_from_r2z2()
        # then
        self.assertIsNone(killmail)

    @pook.on
    def test_should_raise_error_when_unexpected_http_error(self, mock_cache: CacheFake):
        # given
        mock_cache.set(zkb._KEY_LAST_SEQUENCE, 12345)
        pook.get(
            "https://r2z2.zkillboard.com/ephemeral/12345.json",
            reply=500,
            response_json={},
        )
        # when
        with self.assertRaises(requests.exceptions.HTTPError):
            zkb.fetch_killmail_from_r2z2()

    @pook.on
    def test_should_raise_too_many_requests_error(self, mock_cache: CacheFake):
        # given
        mock_cache.set(zkb._KEY_LAST_SEQUENCE, 12345)
        pook.get(
            "https://r2z2.zkillboard.com/ephemeral/12345.json",
            reply=429,
            response_json={},
        )
        # when/then
        with self.assertRaises(zkb.R2Z2TooManyRequestsError):
            zkb.fetch_killmail_from_r2z2()

    @pook.on
    def test_should_reraise_too_many_requests_error_when_ongoing(
        self, mock_cache: CacheFake
    ):
        # given
        retry_at = now() + dt.timedelta(hours=3)
        mock_cache.set(zkb._KEY_RETRY_AT, retry_at)
        mock_cache.set(zkb._KEY_LAST_SEQUENCE, 12345)
        pook.get(
            "https://r2z2.zkillboard.com/ephemeral/12345.json",
            reply=500,
            response_json={},
        )

        # when/then
        self.assertFalse(pook.isdone())
        with self.assertRaises(zkb.R2Z2TooManyRequestsError) as ex:
            zkb.fetch_killmail_from_r2z2()

        self.assertEqual(retry_at, ex.exception.retry_at)

    @pook.on
    def test_should_raise_error_when_api_does_not_return_json(
        self, mock_cache: CacheFake
    ):
        # given
        mock_cache.set(zkb._KEY_LAST_SEQUENCE, 12345)
        pook.get(
            "https://r2z2.zkillboard.com/ephemeral/12345.json",
            reply=200,
            response_body="this is not JSON",
        )
        # when
        with self.assertRaises(requests.exceptions.JSONDecodeError):
            zkb.fetch_killmail_from_r2z2()

    @pook.on
    def test_should_wait_until_next_slot_if_needed(self, mock_cache: CacheFake):
        # given
        sequence_id = 12345
        mock_cache.set(zkb._KEY_LAST_REQUEST, now() + dt.timedelta(seconds=1))
        mock_cache.set(zkb._KEY_LAST_SEQUENCE, sequence_id)
        km_1 = KillmailFactory()
        pook.get(
            f"https://r2z2.zkillboard.com/ephemeral/{sequence_id}.json",
            reply=200,
            response_json=R2Z2ResponseFactory(killmail=km_1, sequence_id=sequence_id),
        )
        # when
        with patch(MODULE_PATH + ".sleep") as mock_sleep:
            km_2 = zkb.fetch_killmail_from_r2z2()
            # then
            self.assertEqual(km_2.id, km_1.id)
            self.assertTrue(mock_sleep.called)


class TestKillmail_Basics(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
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
        cls.killmail = KillmailFactory(
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

    def test_str(self):
        self.assertEqual(str(self.killmail), "Killmail(id=10000001)")

    def test_repr(self):
        self.assertEqual(repr(self.killmail), "Killmail(id=10000001)")

    def test_should_return_attacker_alliance_ids(self):
        # when
        result = self.killmail.attackers_distinct_alliance_ids()
        # then
        self.assertSetEqual(set(result), {3001})

    def test_should_return_attacker_faction_ids(self):
        # when
        result = self.killmail.attackers_distinct_faction_ids()
        # then
        self.assertSetEqual(set(result), {500001})

    def test_should_return_attacker_corporation_ids(self):
        # when
        result = self.killmail.attackers_distinct_corporation_ids()
        # then
        self.assertSetEqual(set(result), {2001})

    def test_should_return_attacker_character_ids(self):
        # when
        result = self.killmail.attackers_distinct_character_ids()
        # then
        self.assertSetEqual(set(result), {1001, 1002, 1003})

    def test_should_return_attacker_ship_type_ids(self):
        self.assertListEqual(
            self.killmail.attackers_ship_type_ids(), [34562, 3756, 3756]
        )

    def test_should_return_attacker_weapon_ship_type_ids(self):
        self.assertListEqual(
            self.killmail.attackers_weapon_type_ids(),
            [2977, 2488, 2488],
        )

    def test_ships_types(self):
        self.assertSetEqual(self.killmail.ship_type_distinct_ids(), {603, 34562, 3756})

    def test_entity_ids(self):
        result = self.killmail.entity_ids()
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


class TestKillmail_Serialization(NoSocketsTestCase):
    def test_dict_serialization(self):
        killmail = KillmailFactory()
        dct_1 = killmail.asdict()
        killmail_2 = Killmail.from_dict(dct_1)
        self.maxDiff = None
        self.assertEqual(killmail, killmail_2)

    def test_json_serialization(self):
        killmail = KillmailFactory()
        json_1 = killmail.asjson()
        killmail_2 = Killmail.from_json(json_1)
        self.maxDiff = None
        self.assertEqual(killmail, killmail_2)


class TestFetchKillmailFromApi(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cache.clear()

    @patch(MODULE_PATH + ".cache", CacheStub())
    @pook.on
    def test_normal(self):
        # given
        killmail_id = 135067522
        attacker_alliance_id = 99009567
        attacker_character_id = 211150393
        attacker_corporation_id = 98407493
        attacker_security_status = 5
        attacker_ship_type_id = 47270
        damage_done = 78928
        damage_taken = 78928
        killmail_hash = "8d2a4c0779bc067e1ec5851feb086c82099cf7dc"
        killmail_time = dt.datetime(2026, 4, 27, 18, 44, 42, 0, tzinfo=dt.timezone.utc)
        solar_system_id = 30001980
        victim_alliance_id = 99003581
        victim_character_id = 2122649889
        victim_corporation_id = 98598862
        victim_faction_id = 500011
        victim_ship_type_id = 24688
        weapon_type_id = 47919
        location_id = 50004638
        fitted_value = 236574722.76
        total_value = 268883360.72
        points = 190
        pook.get(
            f"{_ZKB_API_URL}killID/{killmail_id}/",
            reply=200,
            response_json=[
                {
                    "killmail_id": killmail_id,
                    "zkb": {
                        "locationID": location_id,
                        "hash": killmail_hash,
                        "fittedValue": fitted_value,
                        "droppedValue": 52914789.03,
                        "destroyedValue": 215968571.69,
                        "totalValue": total_value,
                        "points": points,
                        "npc": False,
                        "solo": True,
                        "awox": False,
                        "labels": ["tz:eu", "cat:6", "solo", "pvp", "loc:nullsec"],
                    },
                }
            ],
        )
        pook.get(
            f"https://esi.evetech.net/killmails/{killmail_id}/{killmail_hash}",
            reply=200,
            response_json={
                "attackers": [
                    {
                        "alliance_id": attacker_alliance_id,
                        "character_id": attacker_character_id,
                        "corporation_id": attacker_corporation_id,
                        "damage_done": damage_done,
                        "final_blow": True,
                        "security_status": attacker_security_status,
                        "ship_type_id": attacker_ship_type_id,
                        "weapon_type_id": weapon_type_id,
                    }
                ],
                "killmail_id": killmail_id,
                "killmail_time": killmail_time.isoformat(),
                "solar_system_id": solar_system_id,
                "victim": {
                    "alliance_id": victim_alliance_id,
                    "character_id": victim_character_id,
                    "corporation_id": victim_corporation_id,
                    "damage_taken": damage_taken,
                    "faction_id": victim_faction_id,
                    "items": [],
                    "position": {
                        "x": 3074726066717.27,
                        "y": 356699410448.6995,
                        "z": -383193277301.9448,
                    },
                    "ship_type_id": victim_ship_type_id,
                },
            },
        )

        # when
        killmail = fetch_killmail_from_api(killmail_id)

        # then
        self.assertIsNotNone(killmail)
        self.assertEqual(killmail.id, killmail_id)
        self.assertEqual(killmail.time, killmail_time)

        self.assertEqual(killmail.victim.alliance_id, victim_alliance_id)
        self.assertEqual(killmail.victim.character_id, victim_character_id)
        self.assertEqual(killmail.victim.corporation_id, victim_corporation_id)
        self.assertEqual(killmail.victim.damage_taken, damage_taken)
        self.assertEqual(killmail.victim.ship_type_id, victim_ship_type_id)

        self.assertEqual(len(killmail.attackers), 1)

        attacker_1 = killmail.attackers[0]
        self.assertEqual(attacker_1.alliance_id, attacker_alliance_id)
        self.assertEqual(attacker_1.character_id, attacker_character_id)
        self.assertEqual(attacker_1.corporation_id, attacker_corporation_id)
        self.assertEqual(attacker_1.damage_done, damage_done)
        self.assertEqual(attacker_1.security_status, attacker_security_status)
        self.assertEqual(attacker_1.ship_type_id, attacker_ship_type_id)
        self.assertEqual(attacker_1.weapon_type_id, weapon_type_id)

        self.assertEqual(killmail.zkb.location_id, location_id)
        self.assertEqual(killmail.zkb.fitted_value, fitted_value)
        self.assertEqual(killmail.zkb.total_value, total_value)
        self.assertEqual(killmail.zkb.points, points)
        self.assertFalse(killmail.zkb.is_npc)
        self.assertTrue(killmail.zkb.is_solo)
        self.assertFalse(killmail.zkb.is_awox)


@patch(MODULE_PATH + ".cache", new_callable=CacheFake2)
class TestKillmail_Storage(TestCase):
    def test_should_store_and_retrieve_killmail(self, mock_cache):
        # given
        killmail_1 = KillmailFactory()
        # when
        killmail_1.save()
        killmail_2 = Killmail.get(id=killmail_1.id)
        # then
        self.assertEqual(killmail_1, killmail_2)

    def test_should_raise_error_when_killmail_does_not_exist(self, mock_cache):
        # when/then
        with self.assertRaises(KillmailDoesNotExist):
            Killmail.get(id=99)

    def test_should_delete_killmail(self, mock_cache):
        # given
        killmail = KillmailFactory()
        killmail.save()
        # when
        killmail.delete()
        # then
        with self.assertRaises(KillmailDoesNotExist):
            Killmail.get(id=killmail.id)

    def test_should_override_existing_killmail(self, mock_cache):
        # given
        killmail_1 = KillmailFactory(zkb__points=1)
        killmail_1.save()
        killmail_1.zkb.points = 2
        # when
        killmail_1.save()
        # then
        killmail_2 = Killmail.get(id=killmail_1.id)
        self.assertEqual(killmail_1.id, killmail_2.id)
        self.assertEqual(killmail_2.zkb.points, 2)

    def test_should_delete_all_killmails(self, _):
        # given
        km1 = KillmailFactory()
        km1.save()
        km2 = KillmailFactory()
        km2.save()
        # when
        got = Killmail.delete_all()
        # then
        self.assertEqual(got, 2)
        with self.assertRaises(KillmailDoesNotExist):
            Killmail.get(id=km1.id)
        with self.assertRaises(KillmailDoesNotExist):
            Killmail.get(id=km2.id)


class TestKillmail_CreateFromZkbData(TestCase):
    def test_can_create_from_complete_data(self):
        km = Killmail.create_from_zkb_data(
            42,
            {
                "attackers": [
                    {
                        "alliance_id": 3001,
                        "character_id": 1001,
                        "corporation_id": 2001,
                        "faction_id": 500001,
                        "damage_done": 434,
                        "final_blow": True,
                        "security_status": -10,
                        "ship_type_id": 34562,
                        "weapon_type_id": 2977,
                    },
                    {
                        "alliance_id": 3001,
                        "character_id": 1002,
                        "corporation_id": 2001,
                        "faction_id": 500001,
                        "damage_done": 50,
                        "final_blow": False,
                        "security_status": -10,
                        "ship_type_id": 3756,
                        "weapon_type_id": 2488,
                    },
                ],
                "killmail_id": None,
                "killmail_time": None,
                "solar_system_id": 30004984,
                "moon_id": 40000001,
                "war_id": 666,
                "victim": {
                    "alliance_id": 3011,
                    "character_id": 1011,
                    "corporation_id": 2011,
                    "faction_id": 500004,
                    "damage_taken": 434,
                    "items": [],
                    "position": {
                        "x": -1090788346073.3304,
                        "y": 215361914442.54877,
                        "z": -22223971337.631683,
                    },
                    "ship_type_id": 603,
                },
            },
            {
                "locationID": 50012306,
                "hash": "low sec kill",
                "fittedValue": 10000,
                "totalValue": 10000,
                "points": 1,
                "npc": False,
                "solo": False,
                "awox": False,
                "href": "",
            },
        )
        self.assertEqual(km.id, 42)

    def test_can_create_when_victim_position_missing(self):
        km = Killmail.create_from_zkb_data(
            42,
            {
                "attackers": [
                    {
                        "alliance_id": 3001,
                        "character_id": 1001,
                        "corporation_id": 2001,
                        "faction_id": 500001,
                        "damage_done": 434,
                        "final_blow": True,
                        "security_status": -10,
                        "ship_type_id": 34562,
                        "weapon_type_id": 2977,
                    },
                    {
                        "alliance_id": 3001,
                        "character_id": 1002,
                        "corporation_id": 2001,
                        "faction_id": 500001,
                        "damage_done": 50,
                        "final_blow": False,
                        "security_status": -10,
                        "ship_type_id": 3756,
                        "weapon_type_id": 2488,
                    },
                ],
                "killmail_id": None,
                "killmail_time": None,
                "solar_system_id": 30004984,
                "moon_id": 40000001,
                "war_id": 666,
                "victim": {
                    "alliance_id": 3011,
                    "character_id": 1011,
                    "corporation_id": 2011,
                    "faction_id": 500004,
                    "damage_taken": 434,
                    "items": [],
                    "position": None,
                    "ship_type_id": 603,
                },
            },
            {
                "locationID": 50012306,
                "hash": "low sec kill",
                "fittedValue": 10000,
                "totalValue": 10000,
                "points": 1,
                "npc": False,
                "solo": False,
                "awox": False,
                "href": "",
            },
        )
        self.assertEqual(km.id, 42)

    def test_can_create_when_solar_system_is_missing(self):
        km = Killmail.create_from_zkb_data(
            42,
            {
                "attackers": [
                    {
                        "alliance_id": 3001,
                        "character_id": 1001,
                        "corporation_id": 2001,
                        "faction_id": 500001,
                        "damage_done": 434,
                        "final_blow": True,
                        "security_status": -10,
                        "ship_type_id": 34562,
                        "weapon_type_id": 2977,
                    },
                    {
                        "alliance_id": 3001,
                        "character_id": 1002,
                        "corporation_id": 2001,
                        "faction_id": 500001,
                        "damage_done": 50,
                        "final_blow": False,
                        "security_status": -10,
                        "ship_type_id": 3756,
                        "weapon_type_id": 2488,
                    },
                ],
                "killmail_id": None,
                "killmail_time": None,
                "moon_id": 40000001,
                "war_id": 666,
                "victim": {
                    "alliance_id": 3011,
                    "character_id": 1011,
                    "corporation_id": 2011,
                    "faction_id": 500004,
                    "damage_taken": 434,
                    "items": [],
                    "position": {
                        "x": -1090788346073.3304,
                        "y": 215361914442.54877,
                        "z": -22223971337.631683,
                    },
                    "ship_type_id": 603,
                },
            },
            {
                "locationID": 50012306,
                "hash": "low sec kill",
                "fittedValue": 10000,
                "totalValue": 10000,
                "points": 1,
                "npc": False,
                "solo": False,
                "awox": False,
                "href": "",
            },
        )
        self.assertEqual(km.id, 42)


class TestKillmail_CloneWithTrackerInfo(NoSocketsTestCase):
    def test_can_clone_minimal(self):
        # given
        km_1 = KillmailFactory(attacker_count=1)
        tracker = TrackerFactory()

        # when
        km_2 = km_1.clone_with_tracker_info(tracker_pk=tracker.pk)

        # then
        self.assertEqual(km_2.attackers, km_1.attackers)
        self.assertEqual(km_2.position, km_1.position)
        self.assertEqual(km_2.solar_system_id, km_1.solar_system_id)
        self.assertEqual(km_2.time, km_1.time)
        self.assertEqual(km_2.victim, km_1.victim)
        self.assertEqual(km_2.zkb, km_1.zkb)

        self.assertEqual(km_2.tracker_info.tracker_pk, tracker.pk)
        self.assertIsNone(km_2.tracker_info.jumps)
        self.assertIsNone(km_2.tracker_info.distance)

    def test_can_clone_all_infos(self):
        # given
        km_1 = KillmailFactory(attacker_count=1)
        tracker = TrackerFactory()

        # when
        jumps = 7
        distance = 5.4
        km_2 = km_1.clone_with_tracker_info(
            tracker_pk=tracker.pk, jumps=jumps, distance=distance
        )

        # then
        self.assertEqual(km_2.attackers, km_1.attackers)
        self.assertEqual(km_2.position, km_1.position)
        self.assertEqual(km_2.solar_system_id, km_1.solar_system_id)
        self.assertEqual(km_2.time, km_1.time)
        self.assertEqual(km_2.victim, km_1.victim)
        self.assertEqual(km_2.zkb, km_1.zkb)

        self.assertEqual(km_2.tracker_info.tracker_pk, tracker.pk)
        self.assertEqual(km_2.tracker_info.jumps, jumps)
        self.assertEqual(km_2.tracker_info.distance, distance)

    def test_main_org_should_be_none_when_only_one_attacker(self):
        # given
        km_1 = KillmailFactory(attacker_count=1)
        tracker = TrackerFactory()

        # when
        km_2 = km_1.clone_with_tracker_info(tracker_pk=tracker.pk)

        # then
        self.assertIsNone(km_2.tracker_info.main_org)

    def test_main_should_set_main_org(self):
        # given
        alliance = EveEntityAllianceFactory()
        km_1 = KillmailFactory(
            attackers=[
                KillmailAttackerFactory(alliance_id=alliance.id),
                KillmailAttackerFactory(alliance_id=alliance.id),
                KillmailAttackerFactory(),
            ]
        )
        tracker = TrackerFactory()

        # when
        km_2 = km_1.clone_with_tracker_info(tracker_pk=tracker.pk)

        # then
        self.assertEqual(
            km_2.tracker_info.main_org,
            _EntityCount(
                id=alliance.id,
                category=_EntityCount.CATEGORY_ALLIANCE,
                count=2,
            ),
        )

    def test_main_org_is_none_when_faction_only(self):
        # given
        faction = EveEntityFactionFactory()
        km_1 = KillmailFactory(
            attackers=[
                KillmailAttackerFactory(
                    alliance_id=None, corporation_id=None, faction_id=faction.id
                ),
                KillmailAttackerFactory(
                    alliance_id=None, corporation_id=None, faction_id=faction.id
                ),
            ]
        )
        tracker = TrackerFactory()

        # when
        km_2 = km_1.clone_with_tracker_info(tracker_pk=tracker.pk)

        # then
        self.assertIsNone(km_2.tracker_info.main_org)

    # def test_main_ship_group_above_threshold(self, mock_calc_distances: Mock):
    # def test_main_ship_group_return_none_if_below_threshold(
    # def test_main_org_above_threshold(self, mock_calc_distances: Mock):
    # def test_main_org_return_none_if_below_threshold(self, mock_calc_distances: Mock):
    # def test_should_handle_exceptions_from_eveuniverse(self, mock_calc_distances: Mock):


class TestEntityCount(NoSocketsTestCase):
    def test_is_alliance(self):
        alliance = _EntityCount(1, _EntityCount.CATEGORY_ALLIANCE)
        corporation = _EntityCount(2, _EntityCount.CATEGORY_CORPORATION)

        self.assertTrue(alliance.is_alliance)
        self.assertFalse(corporation.is_alliance)

    def test_is_corporation(self):
        alliance = _EntityCount(1, _EntityCount.CATEGORY_ALLIANCE)
        corporation = _EntityCount(2, _EntityCount.CATEGORY_CORPORATION)

        self.assertFalse(alliance.is_corporation)
        self.assertTrue(corporation.is_corporation)


# ---------
