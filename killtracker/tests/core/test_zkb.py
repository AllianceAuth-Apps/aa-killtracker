import datetime as dt
import fnmatch
import unittest
from unittest.mock import patch

import requests
import requests_mock

from django.test import TestCase
from django.utils.timezone import now

from app_utils.esi_testing import BravadoOperationStub
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
from killtracker.tests.testdata.factories import KillmailFactory
from killtracker.tests.testdata.helpers import killmails_data, load_killmail, r2z2_data

MODULE_PATH = "killtracker.core.zkb"
unittest.util._MAX_LENGTH = 1000
requests_mock.mock.case_sensitive = True


@patch(MODULE_PATH + ".cache", new_callable=CacheFake)
@requests_mock.Mocker()
class TestFetchKillmailFromR2Z2(NoSocketsTestCase):
    def test_should_return_killmail_from_scratch(self, mock_cache, requests_mocker):
        # given
        requests_mocker.register_uri(
            "GET",
            "https://r2z2.zkillboard.com/ephemeral/sequence.json",
            status_code=200,
            json={"sequence": 12345},
        )
        killmails = r2z2_data()
        requests_mocker.register_uri(
            "GET",
            "https://r2z2.zkillboard.com/ephemeral/12345.json",
            status_code=200,
            json=killmails[10000001],
        )
        # when
        killmail = zkb.fetch_killmail_from_r2z2()
        # then
        self.assertIsNotNone(killmail)
        self.assertEqual(killmail.id, 10000001)
        self.assertEqual(killmail.solar_system_id, 30004984)
        self.assertEqual(killmail.moon_id, 40000001)
        self.assertEqual(killmail.war_id, 666)
        self.assertAlmostEqual(killmail.time, now(), delta=dt.timedelta(seconds=120))
        self.assertEqual(killmail.victim.alliance_id, 3011)
        self.assertEqual(killmail.victim.character_id, 1011)
        self.assertEqual(killmail.victim.corporation_id, 2011)
        self.assertEqual(killmail.victim.damage_taken, 434)
        self.assertEqual(killmail.victim.ship_type_id, 603)
        self.assertEqual(len(killmail.attackers), 3)

        attacker_1 = killmail.attackers[0]
        self.assertEqual(attacker_1.alliance_id, 3001)
        self.assertEqual(attacker_1.character_id, 1001)
        self.assertEqual(attacker_1.corporation_id, 2001)
        self.assertEqual(attacker_1.damage_done, 434)
        self.assertEqual(attacker_1.security_status, -10)
        self.assertEqual(attacker_1.ship_type_id, 34562)
        self.assertEqual(attacker_1.weapon_type_id, 2977)

        self.assertEqual(killmail.zkb.location_id, 50012306)
        self.assertEqual(killmail.zkb.fitted_value, 10000)
        self.assertEqual(killmail.zkb.total_value, 10000)
        self.assertEqual(killmail.zkb.points, 1)
        self.assertFalse(killmail.zkb.is_npc)
        self.assertFalse(killmail.zkb.is_solo)
        self.assertFalse(killmail.zkb.is_awox)

    def test_should_return_next_killmail(self, mock_cache, requests_mocker):
        # given
        mock_cache.set(zkb._KEY_LAST_SEQUENCE, 12345)
        requests_mocker.register_uri(
            "GET",
            "https://r2z2.zkillboard.com/ephemeral/12345.json",
            status_code=200,
            json=r2z2_data()[10000001],
        )
        # when
        killmail = zkb.fetch_killmail_from_r2z2()
        # then
        self.assertEqual(killmail.id, 10000001)

    def test_should_return_none_when_api_returns_404(self, mock_cache, requests_mocker):
        # given
        mock_cache.set(zkb._KEY_LAST_SEQUENCE, 12345)
        requests_mocker.register_uri(
            "GET",
            "https://r2z2.zkillboard.com/ephemeral/12345.json",
            status_code=404,
            json={},
        )
        # when
        killmail = zkb.fetch_killmail_from_r2z2()
        # then
        self.assertIsNone(killmail)

    def test_should_ignore_invalid_value_for_retry_at_key(
        self, mock_cache, requests_mocker
    ):
        # given
        mock_cache.set(zkb._KEY_RETRY_AT, "abc")
        mock_cache.set(zkb._KEY_LAST_SEQUENCE, 12345)
        requests_mocker.register_uri(
            "GET",
            "https://r2z2.zkillboard.com/ephemeral/12345.json",
            status_code=404,
            json={},
        )
        # when
        killmail = zkb.fetch_killmail_from_r2z2()
        # then
        self.assertIsNone(killmail)

    def test_should_ignore_invalid_value_for_last_request_key(
        self, mock_cache, requests_mocker
    ):
        # given
        mock_cache.set(zkb._KEY_LAST_REQUEST, "abc")
        mock_cache.set(zkb._KEY_LAST_SEQUENCE, 12345)
        requests_mocker.register_uri(
            "GET",
            "https://r2z2.zkillboard.com/ephemeral/12345.json",
            status_code=404,
            json={},
        )
        # when
        killmail = zkb.fetch_killmail_from_r2z2()
        # then
        self.assertIsNone(killmail)

    def test_should_raise_error_when_unexpected_http_error(
        self, mock_cache, requests_mocker
    ):
        # given
        mock_cache.set(zkb._KEY_LAST_SEQUENCE, 12345)
        requests_mocker.register_uri(
            "GET",
            "https://r2z2.zkillboard.com/ephemeral/12345.json",
            status_code=500,
            json={},
        )
        # when
        with self.assertRaises(requests.exceptions.HTTPError):
            zkb.fetch_killmail_from_r2z2()

    def test_should_raise_too_many_requests_error(self, mock_cache, requests_mocker):
        # given
        mock_cache.set(zkb._KEY_LAST_SEQUENCE, 12345)
        requests_mocker.register_uri(
            "GET",
            "https://r2z2.zkillboard.com/ephemeral/12345.json",
            status_code=429,
            json={},
        )
        # when/then
        with self.assertRaises(zkb.R2Z2TooManyRequestsError):
            zkb.fetch_killmail_from_r2z2()

    def test_should_reraise_too_many_requests_error_when_ongoing(
        self, mock_cache, requests_mocker
    ):
        # given
        retry_at = now() + dt.timedelta(hours=3)
        mock_cache.set(zkb._KEY_RETRY_AT, retry_at)
        mock_cache.set(zkb._KEY_LAST_SEQUENCE, 12345)
        requests_mocker.register_uri(
            "GET",
            "https://r2z2.zkillboard.com/ephemeral/12345.json",
            status_code=500,
            json={},
        )
        # when/then
        self.assertEqual(requests_mocker.call_count, 0)
        with self.assertRaises(zkb.R2Z2TooManyRequestsError) as ex:
            zkb.fetch_killmail_from_r2z2()
        self.assertEqual(retry_at, ex.exception.retry_at)

    def test_should_raise_error_when_api_does_not_return_json(
        self, mock_cache, requests_mocker
    ):
        # given
        mock_cache.set(zkb._KEY_LAST_SEQUENCE, 12345)
        requests_mocker.register_uri(
            "GET",
            "https://r2z2.zkillboard.com/ephemeral/12345.json",
            status_code=200,
            text="this is not JSON",
        )
        # when
        with self.assertRaises(requests.exceptions.JSONDecodeError):
            zkb.fetch_killmail_from_r2z2()

    def test_should_wait_until_next_slot_if_needed(self, mock_cache, requests_mocker):
        # given
        mock_cache.set(zkb._KEY_LAST_REQUEST, now())
        mock_cache.set(zkb._KEY_LAST_SEQUENCE, 12345)
        requests_mocker.register_uri(
            "GET",
            "https://r2z2.zkillboard.com/ephemeral/12345.json",
            status_code=200,
            json=r2z2_data()[10000001],
        )
        # when
        with patch(MODULE_PATH + ".sleep") as mock_sleep:
            killmail = zkb.fetch_killmail_from_r2z2()
            # then
            self.assertEqual(killmail.id, 10000001)
            self.assertTrue(mock_sleep.called)


class TestKillmailSerialization(NoSocketsTestCase):
    def test_dict_serialization(self):
        killmail = load_killmail(10000001)
        dct_1 = killmail.asdict()
        killmail_2 = Killmail.from_dict(dct_1)
        self.maxDiff = None
        self.assertEqual(killmail, killmail_2)

    def test_json_serialization(self):
        killmail = load_killmail(10000001)
        json_1 = killmail.asjson()
        killmail_2 = Killmail.from_json(json_1)
        self.maxDiff = None
        self.assertEqual(killmail, killmail_2)


class TestKillmailBasics(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.killmail = load_killmail(10000001)

    def test_str(self):
        self.assertEqual(str(self.killmail), "Killmail(id=10000001)")

    def test_repr(self):
        self.assertEqual(repr(self.killmail), "Killmail(id=10000001)")

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


@patch(MODULE_PATH + ".cache", CacheStub())
@patch(MODULE_PATH + ".esi")
@requests_mock.Mocker()
class TestCreateFromZkbApi(NoSocketsTestCase):
    def test_normal(self, mock_esi, requests_mocker):
        killmail_id = 10000001
        killmail_data = killmails_data()[killmail_id]
        zkb_api_data = [
            {"killmail_id": killmail_data["killmail_id"], "zkb": killmail_data["zkb"]}
        ]
        requests_mocker.register_uri(
            "GET",
            f"{_ZKB_API_URL}killID/{killmail_id}/",
            status_code=200,
            json=zkb_api_data,
        )
        mock_esi.client.Killmails.get_killmails_killmail_id_killmail_hash.return_value = BravadoOperationStub(
            killmail_data["esi"]
        )

        killmail = fetch_killmail_from_api(killmail_id)
        self.assertIsNotNone(killmail)
        self.assertEqual(killmail.id, killmail_id)
        self.assertAlmostEqual(killmail.time, now(), delta=dt.timedelta(seconds=120))

        self.assertEqual(killmail.victim.alliance_id, 3011)
        self.assertEqual(killmail.victim.character_id, 1011)
        self.assertEqual(killmail.victim.corporation_id, 2011)
        self.assertEqual(killmail.victim.damage_taken, 434)
        self.assertEqual(killmail.victim.ship_type_id, 603)

        self.assertEqual(len(killmail.attackers), 3)

        attacker_1 = killmail.attackers[0]
        self.assertEqual(attacker_1.alliance_id, 3001)
        self.assertEqual(attacker_1.character_id, 1001)
        self.assertEqual(attacker_1.corporation_id, 2001)
        self.assertEqual(attacker_1.damage_done, 434)
        self.assertEqual(attacker_1.security_status, -10)
        self.assertEqual(attacker_1.ship_type_id, 34562)
        self.assertEqual(attacker_1.weapon_type_id, 2977)

        self.assertEqual(killmail.zkb.location_id, 50012306)
        self.assertEqual(killmail.zkb.fitted_value, 10000)
        self.assertEqual(killmail.zkb.total_value, 10000)
        self.assertEqual(killmail.zkb.points, 1)
        self.assertFalse(killmail.zkb.is_npc)
        self.assertFalse(killmail.zkb.is_solo)
        self.assertFalse(killmail.zkb.is_awox)


class CacheFake2(CacheFake):
    def delete_pattern(self, pattern: str, itersize=None) -> None:
        keys = []
        for k in self._cache:
            if fnmatch.fnmatch(k, pattern):
                keys.append(k)
        for k in keys:
            self.delete(k)
        return len(keys)


@patch(MODULE_PATH + ".cache", new_callable=CacheFake2)
class TestKillmailStorage(TestCase):
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


class TestKillmailCreateFromZkbData(TestCase):
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
        self.assertEqual(km.id, 42)
        self.assertEqual(km.id, 42)
