import datetime as dt
import unittest
from unittest.mock import patch

import requests_mock

from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase
from django.utils.dateparse import parse_datetime
from django.utils.timezone import now

from app_utils.esi_testing import BravadoOperationStub
from app_utils.testing import NoSocketsTestCase

from killtracker.core.zkb import (
    _KEY_LAST_REQUEST,
    _KEY_RETRY_AT,
    _ZKB_API_URL,
    _ZKB_REDISQ_URL,
    Killmail,
    KillmailDoesNotExist,
    ZKBTooManyRequestsError,
    _EntityCount,
)
from killtracker.tests import CacheStub
from killtracker.tests.testdata.factories import KillmailFactory
from killtracker.tests.testdata.helpers import killmails_data, load_killmail
from killtracker.tests.utils import CacheFake

MODULE_PATH = "killtracker.core.zkb"
unittest.util._MAX_LENGTH = 1000
requests_mock.mock.case_sensitive = True


@requests_mock.Mocker()
@patch(MODULE_PATH + ".cache", new_callable=CacheFake)
class TestCreateFromZkbRedisq(NoSocketsTestCase):
    @patch(MODULE_PATH + ".KILLTRACKER_QUEUE_ID", "dummy")
    def test_should_return_killmail(self, requests_mocker, mock_cache):
        # given
        requests_mocker.register_uri(
            "GET",
            _ZKB_REDISQ_URL,
            status_code=200,
            json={"package": killmails_data()[10000001]},
        )
        # when
        killmail = Killmail.create_from_zkb_redisq()
        # then
        self.assertIsNotNone(killmail)
        self.assertEqual(killmail.id, 10000001)
        self.assertEqual(killmail.solar_system_id, 30004984)
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

    @patch(MODULE_PATH + ".KILLTRACKER_QUEUE_ID", "dummy")
    def test_should_return_none_when_zkb_returns_empty_package(
        self, requests_mocker, mock_cache
    ):
        # given
        requests_mocker.register_uri(
            "GET", _ZKB_REDISQ_URL, status_code=200, json={"package": None}
        )
        # when
        killmail = Killmail.create_from_zkb_redisq()
        # then
        self.assertIsNone(killmail)

    @patch(MODULE_PATH + ".KILLTRACKER_QUEUE_ID", "dummy")
    def test_should_ignore_invalid_value_for_retry_at_key(
        self, requests_mocker, mock_cache
    ):
        # given
        mock_cache.set(_KEY_RETRY_AT, "abc")
        requests_mocker.register_uri(
            "GET", _ZKB_REDISQ_URL, status_code=200, json={"package": None}
        )
        # when
        killmail = Killmail.create_from_zkb_redisq()
        # then
        self.assertIsNone(killmail)

    @patch(MODULE_PATH + ".KILLTRACKER_QUEUE_ID", "dummy")
    def test_should_ignore_invalid_value_for_last_request_key(
        self, requests_mocker, mock_cache
    ):
        # given
        mock_cache.set(_KEY_LAST_REQUEST, "abc")
        requests_mocker.register_uri(
            "GET", _ZKB_REDISQ_URL, status_code=200, json={"package": None}
        )
        # when
        killmail = Killmail.create_from_zkb_redisq()
        # then
        self.assertIsNone(killmail)

    @patch(MODULE_PATH + ".KILLTRACKER_QUEUE_ID", "dummy")
    def test_should_handle_zkb_data_has_no_solar_system(
        self, requests_mocker, mock_cache
    ):
        # given
        requests_mocker.register_uri(
            "GET",
            _ZKB_REDISQ_URL,
            status_code=200,
            json={"package": killmails_data()[10000402]},
        )
        # when
        killmail = Killmail.create_from_zkb_redisq()
        # then
        self.assertIsNotNone(killmail)

    @patch(MODULE_PATH + ".KILLTRACKER_QUEUE_ID", "dummy")
    def test_should_return_none_when_http_error(self, requests_mocker, mock_cache):
        # given
        requests_mocker.register_uri("GET", _ZKB_REDISQ_URL, status_code=500)
        # when
        killmail = Killmail.create_from_zkb_redisq()
        # then
        self.assertIsNone(killmail)

    @patch(MODULE_PATH + ".KILLTRACKER_QUEUE_ID", "dummy")
    def test_should_return_raise_too_many_requests_error(
        self, requests_mocker, mock_cache
    ):
        # given
        requests_mocker.register_uri(
            "GET", _ZKB_REDISQ_URL, status_code=429, text="429 too many requests"
        )
        # when/then
        with self.assertRaises(ZKBTooManyRequestsError):
            Killmail.create_from_zkb_redisq()

    @patch(MODULE_PATH + ".KILLTRACKER_QUEUE_ID", "dummy")
    def test_should_reraise_too_many_requests_error_when_ongoing(
        self, requests_mocker, mock_cache
    ):
        # given
        retry_at = now() + dt.timedelta(hours=3)
        mock_cache.set(_KEY_RETRY_AT, retry_at)
        requests_mocker.register_uri("GET", _ZKB_REDISQ_URL, status_code=500)
        # when/then
        self.assertEqual(requests_mocker.call_count, 0)
        with self.assertRaises(ZKBTooManyRequestsError) as ex:
            Killmail.create_from_zkb_redisq()
        self.assertEqual(retry_at, ex.exception.retry_at)

    @patch(MODULE_PATH + ".KILLTRACKER_QUEUE_ID", "dummy")
    def test_should_return_none_when_zkb_returns_general_error(
        self, requests_mocker, mock_cache
    ):
        # given
        requests_mocker.register_uri(
            "GET",
            _ZKB_REDISQ_URL,
            status_code=200,
            text="""Your IP has been banned because of excessive errors.

You can only have one request to listen.php in flight at any time, otherwise you will generate a too many requests error (429). If you have too many of these errors you will be banned automatically.""",
        )
        # when
        killmail = Killmail.create_from_zkb_redisq()
        # then
        self.assertIsNone(killmail)

    @patch(MODULE_PATH + ".KILLTRACKER_QUEUE_ID", "dummy")
    def test_should_return_none_when_zkb_does_not_return_json(
        self, requests_mocker, mock_cache
    ):
        # given
        requests_mocker.register_uri(
            "GET", _ZKB_REDISQ_URL, status_code=200, text="this is not JSON"
        )
        # when
        killmail = Killmail.create_from_zkb_redisq()
        # then
        self.assertIsNone(killmail)

    @patch(MODULE_PATH + ".KILLTRACKER_QUEUE_ID", "Voltron9000")
    def test_should_have_queue_id_in_request(self, requests_mocker, mock_cache):
        # given
        requests_mocker.register_uri(
            "GET", _ZKB_REDISQ_URL, status_code=200, json={"package": None}
        )
        # when
        Killmail.create_from_zkb_redisq()
        # then
        qs = requests_mocker.last_request.qs
        self.assertIn("queueID", qs)
        queue_id = qs["queueID"]
        self.assertEqual(len(queue_id), 1)
        self.assertEqual(queue_id[0], "Voltron9000")

    @patch(MODULE_PATH + ".KILLTRACKER_QUEUE_ID", "")
    def test_should_abort_when_no_queue_id_defined(self, requests_mocker, mock_cache):
        # given
        requests_mocker.register_uri(
            "GET", _ZKB_REDISQ_URL, status_code=200, json={"package": None}
        )
        # when/then
        with self.assertRaises(ImproperlyConfigured):
            Killmail.create_from_zkb_redisq()

    @patch(MODULE_PATH + ".KILLTRACKER_QUEUE_ID", "Möchtegern")
    def test_should_urlize_queue_ids(self, requests_mocker, mock_cache):
        # given
        requests_mocker.register_uri(
            "GET", _ZKB_REDISQ_URL, status_code=200, json={"package": None}
        )
        # when
        Killmail.create_from_zkb_redisq()
        # then
        qs = requests_mocker.last_request.qs
        self.assertIn("queueID", qs)
        queue_id = qs["queueID"]
        self.assertEqual(len(queue_id), 1)
        self.assertEqual(queue_id[0], "M%C3%B6chtegern")

    @patch(MODULE_PATH + ".KILLTRACKER_QUEUE_ID", "alpha,bravo")
    def test_should_not_accept_list_for_queue_id(self, requests_mocker, mock_cache):
        # given
        requests_mocker.register_uri(
            "GET", _ZKB_REDISQ_URL, status_code=200, json={"package": None}
        )
        # when/then
        with self.assertRaises(ImproperlyConfigured):
            Killmail.create_from_zkb_redisq()

    @patch(MODULE_PATH + ".sleep")
    @patch(MODULE_PATH + ".KILLTRACKER_QUEUE_ID", "dummy")
    def test_should_wait_until_next_slot_if_needed(
        self, requests_mocker, mock_sleep, mock_cache
    ):
        # given
        mock_cache.set(_KEY_LAST_REQUEST, now())
        requests_mocker.register_uri(
            "GET", _ZKB_REDISQ_URL, status_code=200, json={"package": None}
        )
        # when
        killmail = Killmail.create_from_zkb_redisq()
        # then
        self.assertIsNone(killmail)
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
            {"killmail_id": killmail_data["killID"], "zkb": killmail_data["zkb"]}
        ]
        requests_mocker.register_uri(
            "GET",
            f"{_ZKB_API_URL}killID/{killmail_id}/",
            status_code=200,
            json=zkb_api_data,
        )
        killmail_data["killmail"]["killmail_time"] = parse_datetime(
            killmail_data["killmail"]["killmail_time"]
        )
        mock_esi.client.Killmails.get_killmails_killmail_id_killmail_hash.return_value = BravadoOperationStub(
            killmail_data["killmail"]
        )

        killmail = Killmail.create_from_zkb_api(killmail_id)
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


@patch(MODULE_PATH + ".cache", new_callable=CacheFake)
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
