import json
from datetime import timedelta
from unittest.mock import Mock, patch

from bravado.exception import HTTPNotFound

from django.test import TestCase
from django.utils.timezone import now
from eveuniverse.models import (
    EveConstellation,
    EveGroup,
    EveRegion,
    EveSolarSystem,
    EveType,
)

from allianceauth.eveonline.models import EveAllianceInfo
from allianceauth.tests.auth_utils import AuthUtils
from app_utils.esi_testing import BravadoOperationStub
from app_utils.testdata_factories import (
    EveAllianceInfoFactory,
    EveCorporationInfoFactory,
)
from app_utils.testing import NoSocketsTestCase, add_character_to_user_2

from killtracker.constants import EveGroupId
from killtracker.core.killmails import Killmail, _EntityCount
from killtracker.models import Tracker
from killtracker.tests.testdata.factories import (
    EveFactionInfoFactory,
    KillmailAttackerFactory,
    KillmailFactory,
    KillmailVictimFactory,
    TrackerFactory,
    WebhookFactory,
)
from killtracker.tests.testdata.helpers import LoadTestDataMixin, load_killmail

MODELS_PATH = "killtracker.models"


def esi_get_route_origin_destination(origin, destination, **kwargs) -> list:
    routes = {
        30003067: {
            30003087: [
                30003067,
                30003068,
                30003069,
                30003070,
                30003071,
                30003091,
                30003086,
                30003087,
            ],
            30003070: [30003067, 30003068, 30003069, 30003070],
            30003067: [30003067],
        },
    }
    if origin in routes and destination in routes[origin]:
        return BravadoOperationStub(routes[origin][destination])
    else:
        raise HTTPNotFound(Mock(**{"response.status_code": 404}))


class TestTrackerCalculate(LoadTestDataMixin, NoSocketsTestCase):
    @classmethod
    def _matching_killmail_ids(cls, tracker: Tracker, killmail_ids: set) -> set:
        return {
            killmail.id for killmail in cls._matching_killmails(tracker, killmail_ids)
        }

    @staticmethod
    def _matching_killmails(tracker: Tracker, killmail_ids: set) -> list:
        results = []
        for killmail_id in killmail_ids:
            killmail = load_killmail(killmail_id)
            new_killmail = tracker.process_killmail(killmail)
            if new_killmail:
                results.append(new_killmail)
        return results

    def test_can_match_all(self):
        killmail_ids = {10000001, 10000002, 10000003, 10000004, 10000005}
        tracker = TrackerFactory(webhook=self.webhook_1)
        results = self._matching_killmail_ids(tracker, killmail_ids)
        expected = {10000001, 10000002, 10000003, 10000004, 10000005}
        self.assertSetEqual(results, expected)

    @patch(MODELS_PATH + ".trackers.KILLTRACKER_KILLMAIL_MAX_AGE_FOR_TRACKER", 60)
    def test_excludes_older_killmails(self):
        tracker = TrackerFactory(
            name="Test",
            webhook=self.webhook_1,
        )
        killmail_1 = load_killmail(10000001)
        killmail_2 = load_killmail(10000002)
        killmail_2.time = now() - timedelta(hours=1, seconds=1)
        results = set()
        for killmail in [killmail_1, killmail_2]:
            if tracker.process_killmail(killmail):
                results.add(killmail.id)

        expected = {10000001}
        self.assertSetEqual(results, expected)

    def test_can_process_killmail_without_solar_system(self):
        tracker = TrackerFactory(exclude_high_sec=True, webhook=self.webhook_1)
        self.assertIsNotNone(tracker.process_killmail(load_killmail(10000402)))

    def test_can_filter_high_sec_kills(self):
        killmail_ids = {10000001, 10000002, 10000003, 10000004}
        tracker = TrackerFactory(exclude_high_sec=True, webhook=self.webhook_1)
        results = self._matching_killmail_ids(tracker, killmail_ids)
        expected = {10000001, 10000003, 10000004}
        self.assertSetEqual(results, expected)

    def test_can_filter_low_sec_kills(self):
        killmail_ids = {10000001, 10000002, 10000003, 10000004}
        tracker = TrackerFactory(exclude_low_sec=True, webhook=self.webhook_1)
        results = self._matching_killmail_ids(tracker, killmail_ids)
        expected = {10000002, 10000003, 10000004}
        self.assertSetEqual(results, expected)

    def test_can_filter_null_sec_kills(self):
        killmail_ids = {10000001, 10000002, 10000003, 10000004}
        tracker = TrackerFactory(exclude_null_sec=True, webhook=self.webhook_1)
        results = self._matching_killmail_ids(tracker, killmail_ids)
        expected = {10000001, 10000002, 10000004}
        self.assertSetEqual(results, expected)

    def test_can_filter_w_space_kills(self):
        killmail_ids = {10000001, 10000002, 10000003, 10000004}
        tracker = TrackerFactory(exclude_w_space=True, webhook=self.webhook_1)
        results = self._matching_killmail_ids(tracker, killmail_ids)
        expected = {10000001, 10000002, 10000003}
        self.assertSetEqual(results, expected)

    def test_can_filter_min_attackers(self):
        killmail_ids = {10000001, 10000002, 10000003, 10000004}
        tracker = TrackerFactory(require_min_attackers=3, webhook=self.webhook_1)
        results = self._matching_killmail_ids(tracker, killmail_ids)
        expected = {10000001}
        self.assertSetEqual(results, expected)

    def test_can_filter_max_attackers(self):
        killmail_ids = {10000001, 10000002, 10000003, 10000004}
        tracker = TrackerFactory(require_max_attackers=2, webhook=self.webhook_1)
        results = self._matching_killmail_ids(tracker, killmail_ids)
        expected = {10000002, 10000003, 10000004}
        self.assertSetEqual(results, expected)

    @patch("eveuniverse.models.universe_2.esi")
    def test_can_filter_max_jumps(self, mock_esi):
        mock_esi.client.Routes.get_route_origin_destination.side_effect = (
            esi_get_route_origin_destination
        )

        killmail_ids = {10000101, 10000102, 10000103}
        tracker = TrackerFactory(
            origin_solar_system_id=30003067,
            require_max_jumps=3,
            webhook=self.webhook_1,
        )
        results = self._matching_killmail_ids(tracker, killmail_ids)
        expected = {10000102, 10000103}
        self.assertSetEqual(results, expected)

    @patch("eveuniverse.models.universe_2.esi")
    def test_can_filter_max_distance(self, mock_esi):
        mock_esi.client.Routes.get_route_origin_destination.side_effect = (
            esi_get_route_origin_destination
        )

        killmail_ids = {10000101, 10000102, 10000103}
        tracker = TrackerFactory(
            origin_solar_system_id=30003067,
            require_max_distance=2,
            webhook=self.webhook_1,
        )
        results = self._matching_killmail_ids(tracker, killmail_ids)
        expected = {10000102, 10000103}
        self.assertSetEqual(results, expected)

    def test_can_filter_nullsec_and_attacker_alliance(self):
        killmail_ids = {10000001, 10000002, 10000003, 10000004, 10000005}
        tracker = TrackerFactory(exclude_null_sec=True, webhook=self.webhook_1)
        excluded_alliance = EveAllianceInfo.objects.get(alliance_id=3001)
        tracker.require_attacker_alliances.add(excluded_alliance)
        results = self._matching_killmail_ids(tracker, killmail_ids)
        expected = {10000001, 10000002, 10000004}
        self.assertSetEqual(results, expected)

    def test_can_require_region(self):
        killmail_ids = {10000001, 10000002, 10000003, 10000004}
        tracker = TrackerFactory(webhook=self.webhook_1)
        tracker.require_regions.add(EveRegion.objects.get(id=10000014))
        results = self._matching_killmail_ids(tracker, killmail_ids)
        expected = {10000003}
        self.assertSetEqual(results, expected)

    def test_can_require_constellation(self):
        killmail_ids = {10000001, 10000002, 10000003, 10000004}
        tracker = TrackerFactory(webhook=self.webhook_1)
        tracker.require_constellations.add(EveConstellation.objects.get(id=20000169))
        results = self._matching_killmail_ids(tracker, killmail_ids)
        expected = {10000003}
        self.assertSetEqual(results, expected)

    def test_can_require_solar_system(self):
        killmail_ids = {10000001, 10000002, 10000003, 10000004}
        tracker = TrackerFactory(webhook=self.webhook_1)
        tracker.require_solar_systems.add(EveSolarSystem.objects.get(id=30001161))
        results = self._matching_killmail_ids(tracker, killmail_ids)
        expected = {10000003}
        self.assertSetEqual(results, expected)

    def test_can_require_attackers_ship_groups(self):
        killmail_ids = {10000101, 10000201}
        tracker = TrackerFactory(webhook=self.webhook_1)
        frigate = EveGroup.objects.get(id=EveGroupId.FRIGATE)
        td3s = EveGroup.objects.get(id=EveGroupId.TACTICAL_DESTROYER)
        tracker.require_attackers_ship_groups.add(frigate)
        tracker.require_attackers_ship_groups.add(td3s)
        results = self._matching_killmails(tracker, killmail_ids)
        self.assertEqual(len(results), 1)
        killmail = results[0]
        self.assertEqual(killmail.id, 10000101)
        self.assertListEqual(killmail.tracker_info.matching_ship_type_ids, [34562])

    def test_can_require_victim_ship_group(self):
        killmail_ids = {10000101, 10000201}
        tracker = TrackerFactory(webhook=self.webhook_1)
        td3s = EveGroup.objects.get(id=EveGroupId.TACTICAL_DESTROYER)
        tracker.require_victim_ship_groups.add(td3s)
        results = self._matching_killmails(tracker, killmail_ids)
        self.assertEqual(len(results), 1)
        killmail = results[0]
        self.assertEqual(killmail.id, 10000101)
        self.assertListEqual(killmail.tracker_info.matching_ship_type_ids, [34562])

    def test_can_require_victim_ship_types(self):
        killmail_ids = {10000101, 10000201}
        tracker = TrackerFactory(webhook=self.webhook_1)
        svipul = EveType.objects.get(id=34562)
        tracker.require_victim_ship_types.add(svipul)
        results = self._matching_killmails(tracker, killmail_ids)
        self.assertEqual(len(results), 1)
        killmail = results[0]
        self.assertEqual(killmail.id, 10000101)
        self.assertListEqual(killmail.tracker_info.matching_ship_type_ids, [34562])

    def test_can_require_attackers_ship_types(self):
        """
        when filtering for attackers with ship groups of Frigate, TD3
        then tracker finds killmail that has attacker with TD3 and no attacker with frigate
        and ignores killmail that attackers with neither
        """
        killmail_ids = {10000101, 10000201}
        tracker = TrackerFactory(webhook=self.webhook_1)
        svipul = EveType.objects.get(id=34562)
        tracker.require_attackers_ship_types.add(svipul)
        results = self._matching_killmails(tracker, killmail_ids)
        self.assertEqual(len(results), 1)
        killmail = results[0]
        self.assertEqual(killmail.id, 10000101)
        self.assertListEqual(killmail.tracker_info.matching_ship_type_ids, [34562])

    def test_can_exclude_npc_kills(self):
        killmail_ids = {10000001, 10000002, 10000003, 10000004, 10000005, 10000301}
        tracker = TrackerFactory(webhook=self.webhook_1, exclude_npc_kills=True)
        results = self._matching_killmail_ids(tracker, killmail_ids)
        expected = {10000001, 10000002, 10000003, 10000004, 10000005}
        self.assertSetEqual(results, expected)

    def test_can_require_npc_kills(self):
        killmail_ids = {10000001, 10000002, 10000003, 10000004, 10000005, 10000301}
        tracker = TrackerFactory(webhook=self.webhook_1, require_npc_kills=True)
        results = self._matching_killmail_ids(tracker, killmail_ids)
        expected = {10000301}
        self.assertSetEqual(results, expected)

    def test_should_apply_require_attackers_states(self):
        # given
        killmail_ids = {10000001, 10000002, 10000003, 10000004, 10000005}
        tracker = TrackerFactory(webhook=self.webhook_1)
        tracker.require_attacker_states.add(self.state_member)
        user = AuthUtils.create_member("Lex Luther")
        add_character_to_user_2(user, 1011, "Lex Luthor", 2011, "LexCorp")
        # when
        results = self._matching_killmail_ids(tracker, killmail_ids)
        # then
        self.assertSetEqual(results, {10000005})

    def test_should_apply_exclude_attacker_states(self):
        # given
        killmail_ids = {10000001, 10000002, 10000003, 10000004, 10000005}
        tracker = TrackerFactory(webhook=self.webhook_1)
        tracker.exclude_attacker_states.add(self.state_member)
        user = AuthUtils.create_member("Lex Luther")
        add_character_to_user_2(user, 1011, "Lex Luthor", 2011, "LexCorp")
        # when
        results = self._matching_killmail_ids(tracker, killmail_ids)
        # then
        self.assertSetEqual(results, {10000001, 10000002, 10000003, 10000004})

    def test_should_apply_require_victim_states(self):
        # given
        killmail_ids = {10000003, 10000004, 10000005}
        tracker = TrackerFactory(webhook=self.webhook_1)
        tracker.require_victim_states.add(self.state_member)
        user = AuthUtils.create_member("Lex Luther")
        add_character_to_user_2(user, 1011, "Lex Luthor", 2011, "LexCorp")
        # when
        results = self._matching_killmail_ids(tracker, killmail_ids)
        # then
        self.assertSetEqual(results, {10000003, 10000004})


class TestTrackerCalculate2(LoadTestDataMixin, NoSocketsTestCase):
    def test_should_deny_when_value_is_below_minimum(self):
        killmail = KillmailFactory(zkb__total_value=50_000_000)
        tracker = TrackerFactory(require_min_value=51, webhook=self.webhook_1)
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNone(result)

    def test_should_threat_no_value_as_zero(self):
        killmail = KillmailFactory(zkb__total_value=None)
        tracker = TrackerFactory(require_min_value=51, webhook=self.webhook_1)
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNone(result)

    def test_should_accept_with_require_attacker_weapon_group(self):
        attacker = KillmailAttackerFactory(weapon_type_id=2977)
        killmail = KillmailFactory(attackers=[attacker])
        tracker = TrackerFactory(webhook=self.webhook_1)
        tracker.require_attackers_weapon_groups.add(
            EveGroup.objects.get(id=EveGroupId.PROJECTILE_WEAPON)
        )
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertEqual(killmail.id, result.id)

    def test_should_deny_with_require_attacker_weapon_group(self):
        attacker = KillmailAttackerFactory(weapon_type_id=2488)
        killmail = KillmailFactory(attackers=[attacker])
        tracker = TrackerFactory(webhook=self.webhook_1)
        tracker.require_attackers_weapon_groups.add(
            EveGroup.objects.get(id=EveGroupId.PROJECTILE_WEAPON)
        )
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNone(result)

    def test_should_accept_with_require_attacker_weapon_type(self):
        attacker = KillmailAttackerFactory(weapon_type_id=2977)
        killmail = KillmailFactory(attackers=[attacker])
        tracker = TrackerFactory(webhook=self.webhook_1)
        tracker.require_attackers_weapon_types.add(EveType.objects.get(id=2977))
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertEqual(killmail.id, result.id)

    def test_should_deny_with_require_attacker_weapon_type(self):
        attacker = KillmailAttackerFactory(weapon_type_id=2488)
        killmail = KillmailFactory(attackers=[attacker])
        tracker = TrackerFactory(webhook=self.webhook_1)
        tracker.require_attackers_weapon_types.add(EveType.objects.get(id=2977))
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNone(result)


class TestTrackerCalculateAlliances(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.alliance_1 = EveAllianceInfoFactory()
        cls.alliance_2 = EveAllianceInfoFactory()
        cls.webhook = WebhookFactory()

    def test_should_accept_with_require_attacker_alliances(self):
        attacker = KillmailAttackerFactory(alliance_id=self.alliance_1.alliance_id)
        killmail = KillmailFactory(attackers=[attacker])
        tracker = TrackerFactory(webhook=self.webhook)
        tracker.require_attacker_alliances.add(self.alliance_1)
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNotNone(result)

    def test_should_deny_with_require_attacker_alliances(self):
        attacker = KillmailAttackerFactory(alliance_id=self.alliance_2.alliance_id)
        killmail = KillmailFactory(attackers=[attacker])
        tracker = TrackerFactory(webhook=self.webhook)
        tracker.require_attacker_alliances.add(self.alliance_1)
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNone(result)

    def test_should_accept_with_exclude_attacker_alliances(self):
        attacker = KillmailAttackerFactory(alliance_id=self.alliance_2.alliance_id)
        killmail = KillmailFactory(attackers=[attacker])
        tracker = TrackerFactory(webhook=self.webhook)
        tracker.exclude_attacker_alliances.add(self.alliance_1)
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNotNone(result)

    def test_should_deny_with_exclude_attacker_alliances(self):
        attacker = KillmailAttackerFactory(alliance_id=self.alliance_1.alliance_id)
        killmail = KillmailFactory(attackers=[attacker])
        tracker = TrackerFactory(webhook=self.webhook)
        tracker.exclude_attacker_alliances.add(self.alliance_1)
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNone(result)

    def test_should_accept_when_required_attacker_alliance_has_final_blow(self):
        attacker = KillmailAttackerFactory(
            alliance_id=self.alliance_1.alliance_id, is_final_blow=True
        )
        killmail = KillmailFactory(attackers=[attacker])
        tracker = TrackerFactory(
            require_attacker_organizations_final_blow=True, webhook=self.webhook
        )
        tracker.require_attacker_alliances.add(self.alliance_1)
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNotNone(result)

    def test_should_deny_when_required_attacker_alliance_has_not_final_blow(self):
        attacker_1 = KillmailAttackerFactory(
            alliance_id=self.alliance_1.alliance_id, is_final_blow=False
        )
        attacker_2 = KillmailAttackerFactory(
            alliance_id=self.alliance_2.alliance_id, is_final_blow=True
        )
        killmail = KillmailFactory(attackers=[attacker_1, attacker_2])
        tracker = TrackerFactory(
            require_attacker_organizations_final_blow=True, webhook=self.webhook
        )
        tracker.require_attacker_alliances.add(self.alliance_1)
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNone(result)

    def test_should_deny_with_require_victim_alliance(self):
        victim = KillmailVictimFactory(alliance_id=self.alliance_2.alliance_id)
        killmail = KillmailFactory(victim=victim)
        tracker = TrackerFactory(webhook=self.webhook)
        tracker.require_victim_alliances.add(self.alliance_1)
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNone(result)

    def test_should_accept_with_require_victim_alliance(self):
        victim = KillmailVictimFactory(alliance_id=self.alliance_1.alliance_id)
        killmail = KillmailFactory(victim=victim)
        tracker = TrackerFactory(webhook=self.webhook)
        tracker.require_victim_alliances.add(self.alliance_1)
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNotNone(result)

    def test_should_deny_with_exclude_victim_alliance(self):
        victim = KillmailVictimFactory(alliance_id=self.alliance_1.alliance_id)
        killmail = KillmailFactory(victim=victim)
        tracker = TrackerFactory(webhook=self.webhook)
        tracker.exclude_victim_alliances.add(self.alliance_1)
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNone(result)

    def test_should_accept_with_exclude_victim_alliance(self):
        victim = KillmailVictimFactory(alliance_id=self.alliance_2.alliance_id)
        killmail = KillmailFactory(victim=victim)
        tracker = TrackerFactory(webhook=self.webhook)
        tracker.exclude_victim_alliances.add(self.alliance_1)
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNotNone(result)


class TestTrackerCalculateCorporations(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.corporation_1 = EveCorporationInfoFactory()
        cls.corporation_2 = EveCorporationInfoFactory()
        cls.webhook = WebhookFactory()

    def test_should_accept_with_require_attacker_corporations(self):
        attacker = KillmailAttackerFactory(
            corporation_id=self.corporation_1.corporation_id
        )
        killmail = KillmailFactory(attackers=[attacker])
        tracker = TrackerFactory(webhook=self.webhook)
        tracker.require_attacker_corporations.add(self.corporation_1)
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNotNone(result)

    def test_should_deny_with_require_attacker_corporations(self):
        attacker = KillmailAttackerFactory(
            corporation_id=self.corporation_2.corporation_id
        )
        killmail = KillmailFactory(attackers=[attacker])
        tracker = TrackerFactory(webhook=self.webhook)
        tracker.require_attacker_corporations.add(self.corporation_1)
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNone(result)

    def test_should_accept_with_exclude_attacker_corporations(self):
        attacker = KillmailAttackerFactory(
            corporation_id=self.corporation_2.corporation_id
        )
        killmail = KillmailFactory(attackers=[attacker])
        tracker = TrackerFactory(webhook=self.webhook)
        tracker.exclude_attacker_corporations.add(self.corporation_1)
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNotNone(result)

    def test_should_deny_with_exclude_attacker_corporations(self):
        attacker = KillmailAttackerFactory(
            corporation_id=self.corporation_1.corporation_id
        )
        killmail = KillmailFactory(attackers=[attacker])
        tracker = TrackerFactory(webhook=self.webhook)
        tracker.exclude_attacker_corporations.add(self.corporation_1)
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNone(result)

    def test_should_accept_when_required_attacker_corporation_has_final_blow(self):
        attacker = KillmailAttackerFactory(
            corporation_id=self.corporation_1.corporation_id, is_final_blow=True
        )
        killmail = KillmailFactory(attackers=[attacker])
        tracker = TrackerFactory(
            require_attacker_organizations_final_blow=True, webhook=self.webhook
        )
        tracker.require_attacker_corporations.add(self.corporation_1)
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNotNone(result)

    def test_should_deny_when_required_attacker_corporation_has_not_has_final_blow(
        self,
    ):
        attacker_1 = KillmailAttackerFactory(
            corporation_id=self.corporation_1.corporation_id, is_final_blow=False
        )
        attacker_2 = KillmailAttackerFactory(
            corporation_id=self.corporation_2.corporation_id, is_final_blow=True
        )
        killmail = KillmailFactory(attackers=[attacker_1, attacker_2])
        tracker = TrackerFactory(
            require_attacker_organizations_final_blow=True, webhook=self.webhook
        )
        tracker.require_attacker_corporations.add(self.corporation_1)
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNone(result)

    def test_should_deny_with_require_victim_corporation(self):
        victim = KillmailVictimFactory(corporation_id=self.corporation_2.corporation_id)
        killmail = KillmailFactory(victim=victim)
        tracker = TrackerFactory(webhook=self.webhook)
        tracker.require_victim_corporations.add(self.corporation_1)
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNone(result)

    def test_should_accept_with_require_victim_corporation(self):
        victim = KillmailVictimFactory(corporation_id=self.corporation_1.corporation_id)
        killmail = KillmailFactory(victim=victim)
        tracker = TrackerFactory(webhook=self.webhook)
        tracker.require_victim_corporations.add(self.corporation_1)
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNotNone(result)

    def test_should_deny_with_exclude_victim_corporation(self):
        victim = KillmailVictimFactory(corporation_id=self.corporation_1.corporation_id)
        killmail = KillmailFactory(victim=victim)
        tracker = TrackerFactory(webhook=self.webhook)
        tracker.exclude_victim_corporations.add(self.corporation_1)
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNone(result)

    def test_should_accept_with_exclude_victim_corporation(self):
        victim = KillmailVictimFactory(corporation_id=self.corporation_2.corporation_id)
        killmail = KillmailFactory(victim=victim)
        tracker = TrackerFactory(webhook=self.webhook)
        tracker.exclude_victim_corporations.add(self.corporation_1)
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNotNone(result)


class TestTrackerCalculateFactions(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.faction_1 = EveFactionInfoFactory()
        cls.faction_2 = EveFactionInfoFactory()
        cls.webhook = WebhookFactory()

    def test_should_accept_with_require_attacker_factions(self):
        attacker = KillmailAttackerFactory(faction_id=self.faction_1.faction_id)
        killmail = KillmailFactory(attackers=[attacker])
        tracker = TrackerFactory(webhook=self.webhook)
        tracker.require_attacker_factions.add(self.faction_1)
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNotNone(result)

    def test_should_deny_with_require_attacker_factions(self):
        attacker = KillmailAttackerFactory(faction_id=self.faction_1.faction_id)
        killmail = KillmailFactory(attackers=[attacker])
        tracker = TrackerFactory(webhook=self.webhook)
        tracker.require_attacker_factions.add(self.faction_2)
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNone(result)

    def test_should_accept_with_exclude_attacker_factions(self):
        attacker = KillmailAttackerFactory(faction_id=self.faction_1.faction_id)
        killmail = KillmailFactory(attackers=[attacker])
        tracker = TrackerFactory(webhook=self.webhook)
        tracker.exclude_attacker_factions.add(self.faction_2)
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNotNone(result)

    def test_should_deny_with_exclude_attacker_factions(self):
        attacker = KillmailAttackerFactory(faction_id=self.faction_1.faction_id)
        killmail = KillmailFactory(attackers=[attacker])
        tracker = TrackerFactory(webhook=self.webhook)
        tracker.exclude_attacker_factions.add(self.faction_1)
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNone(result)

    def test_should_accept_with_require_victim_factions(self):
        victim = KillmailVictimFactory(faction_id=self.faction_1.faction_id)
        killmail = KillmailFactory(victim=victim)
        tracker = TrackerFactory(webhook=self.webhook)
        tracker.require_victim_factions.add(self.faction_1)
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNotNone(result)

    def test_should_deny_with_require_victim_factions(self):
        victim = KillmailVictimFactory(faction_id=self.faction_1.faction_id)
        killmail = KillmailFactory(victim=victim)
        tracker = TrackerFactory(webhook=self.webhook)
        tracker.require_victim_factions.add(self.faction_2)
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNone(result)

    def test_should_accept_with_exclude_victim_factions(self):
        victim = KillmailVictimFactory(faction_id=self.faction_1.faction_id)
        killmail = KillmailFactory(victim=victim)
        tracker = TrackerFactory(webhook=self.webhook)
        tracker.exclude_victim_factions.add(self.faction_2)
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNotNone(result)

    def test_should_deny_with_exclude_victim_factions(self):
        victim = KillmailVictimFactory(faction_id=self.faction_1.faction_id)
        killmail = KillmailFactory(victim=victim)
        tracker = TrackerFactory(webhook=self.webhook)
        tracker.exclude_victim_factions.add(self.faction_1)
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNone(result)


# class TestTrackerCalculateStates(NoSocketsTestCase):
#     @classmethod
#     def setUpClass(cls):
#         super().setUpClass()
#         cls.user = UserMainFactory()
#         cls.corporation_1 = EveCorporationInfoFactory()
#         cls.state_1 = AuthUtils.create_state("state_1", priority=200)
#         cls.state_1.member_corporations.add(cls.corporation_1)
#         cls.corporation_2 = EveCorporationInfoFactory()
#         cls.state_2 = AuthUtils.create_state("state_2", priority=150)
#         cls.state_2.member_corporations.add(cls.corporation_2)
#         cls.webhook = WebhookFactory()

#     def test_should_accept_with_require_attacker_states(self):
#         attacker = KillmailAttackerFactory(
#             corporation_id=self.corporation_1.corporation_id
#         )
#         killmail = KillmailFactory(attackers=[attacker])
#         tracker = TrackerFactory(webhook=self.webhook)
#         tracker.require_attacker_states.add(self.state_1)
#         # when
#         result = tracker.process_killmail(killmail)
#         # then
#         self.assertIsNotNone(result)

#     def test_should_deny_with_require_attacker_states(self):
#         attacker = KillmailAttackerFactory(
#             corporation_id=self.corporation_2.corporation_id
#         )
#         killmail = KillmailFactory(attackers=[attacker])
#         tracker = TrackerFactory(webhook=self.webhook)
#         tracker.require_attacker_states.add(self.state_1)
#         # when
#         result = tracker.process_killmail(killmail)
#         # then
#         self.assertIsNotNone(result)


@patch(MODELS_PATH + ".trackers.EveSolarSystem.jumps_to")
class TestTrackerCalculateTrackerInfo(LoadTestDataMixin, NoSocketsTestCase):
    def setUp(self) -> None:
        self.tracker = TrackerFactory(webhook=self.webhook_1)

    def test_basics(self, mock_jumps_to):
        # given
        mock_jumps_to.return_value = 7
        self.tracker.origin_solar_system_id = 30003067
        self.tracker.save()
        # when
        killmail = self.tracker.process_killmail(load_killmail(10000101))
        # then
        self.assertTrue(killmail.tracker_info)
        self.assertEqual(killmail.tracker_info.tracker_pk, self.tracker.pk)
        self.assertEqual(killmail.tracker_info.jumps, 7)
        self.assertAlmostEqual(killmail.tracker_info.distance, 5.85, delta=0.01)
        self.assertEqual(
            killmail.tracker_info.main_org,
            _EntityCount(id=3001, category=_EntityCount.CATEGORY_ALLIANCE, count=3),
        )
        self.assertEqual(
            killmail.tracker_info.main_ship_group,
            _EntityCount(
                id=419,
                category=_EntityCount.CATEGORY_INVENTORY_GROUP,
                name="Combat Battlecruiser",
                count=2,
            ),
        )

    def test_main_org_corporation_is_main(self, mock_jumps_to):
        killmail = self.tracker.process_killmail(load_killmail(10000403))
        self.assertEqual(
            killmail.tracker_info.main_org,
            _EntityCount(id=2001, category=_EntityCount.CATEGORY_CORPORATION, count=2),
        )

    def test_main_org_prioritize_alliance_over_corporation(self, mock_jumps_to):
        killmail = self.tracker.process_killmail(load_killmail(10000401))
        self.assertEqual(
            killmail.tracker_info.main_org,
            _EntityCount(id=3001, category=_EntityCount.CATEGORY_ALLIANCE, count=2),
        )

    def test_main_org_is_none_if_only_one_attacker(self, mock_jumps_to):
        killmail = self.tracker.process_killmail(load_killmail(10000005))
        self.assertIsNone(killmail.tracker_info.main_org)

    def test_main_org_is_none_if_faction(self, mock_jumps_to):
        killmail = self.tracker.process_killmail(load_killmail(10000302))
        self.assertIsNone(killmail.tracker_info.main_org)

    def test_main_ship_group_above_threshold(self, mock_jumps_to):
        killmail = self.tracker.process_killmail(load_killmail(10006001))
        self.assertEqual(
            killmail.tracker_info.main_ship_group,
            _EntityCount(
                id=419, category="inventory_group", name="Combat Battlecruiser", count=2
            ),
        )

    def test_main_ship_group_return_none_if_below_threshold(self, mock_jumps_to):
        killmail = self.tracker.process_killmail(load_killmail(10006002))
        self.assertIsNone(killmail.tracker_info.main_ship_group)

    def test_main_org_above_threshold(self, mock_jumps_to):
        killmail = self.tracker.process_killmail(load_killmail(10006003))
        self.assertEqual(
            killmail.tracker_info.main_org,
            _EntityCount(id=2001, category="corporation", count=2),
        )

    def test_main_org_return_none_if_below_threshold(self, mock_jumps_to):
        killmail = self.tracker.process_killmail(load_killmail(10006004))
        self.assertIsNone(killmail.tracker_info.main_org)

    def test_should_ignore_os_error_esi_route_endpoint(self, mock_jumps_to):
        # given
        mock_jumps_to.side_effect = OSError
        self.tracker.origin_solar_system_id = 30003067
        self.tracker.save()
        # when
        killmail = self.tracker.process_killmail(load_killmail(10000101))
        # then
        self.assertTrue(killmail.tracker_info)
        self.assertEqual(killmail.tracker_info.tracker_pk, self.tracker.pk)
        self.assertIsNone(killmail.tracker_info.jumps)


class TestTrackerEnqueueKillmail(LoadTestDataMixin, TestCase):
    def setUp(self) -> None:
        self.tracker = TrackerFactory(name="My Tracker", webhook=self.webhook_1)
        self.webhook_1.main_queue.clear()

    @patch(MODELS_PATH + ".webhooks.KILLTRACKER_WEBHOOK_SET_AVATAR", True)
    @patch("eveuniverse.models.universe_2.esi")
    def test_normal(self, mock_esi):
        mock_esi.client.Routes.get_route_origin_destination.side_effect = (
            esi_get_route_origin_destination
        )
        self.tracker.origin_solar_system_id = 30003067
        self.tracker.save()
        svipul = EveType.objects.get(id=34562)
        self.tracker.require_attackers_ship_types.add(svipul)
        gnosis = EveType.objects.get(id=3756)
        self.tracker.require_attackers_ship_types.add(gnosis)
        killmail = self.tracker.process_killmail(load_killmail(10000101))

        self.tracker.generate_killmail_message(Killmail.from_json(killmail.asjson()))

        self.assertEqual(self.webhook_1.main_queue.size(), 1)
        message = json.loads(self.webhook_1.main_queue.dequeue())

        self.assertEqual(message["username"], "Killtracker")
        self.assertIsNotNone(message["avatar_url"])
        self.assertIn("My Tracker", message["content"])
        embed = message["embeds"][0]
        self.assertIn("| Killmail", embed["title"])
        self.assertIn("Combat Battlecruiser", embed["description"])
        self.assertIn("Tracked ship types", embed["description"])

    @patch(MODELS_PATH + ".webhooks.KILLTRACKER_WEBHOOK_SET_AVATAR", False)
    @patch("eveuniverse.models.universe_2.esi")
    def test_disabled_avatar(self, mock_esi):
        mock_esi.client.Routes.get_route_origin_destination.side_effect = (
            esi_get_route_origin_destination
        )
        self.tracker.origin_solar_system_id = 30003067
        self.tracker.save()
        svipul = EveType.objects.get(id=34562)
        self.tracker.require_attackers_ship_types.add(svipul)
        gnosis = EveType.objects.get(id=3756)
        self.tracker.require_attackers_ship_types.add(gnosis)
        killmail = self.tracker.process_killmail(load_killmail(10000101))

        self.tracker.generate_killmail_message(Killmail.from_json(killmail.asjson()))

        self.assertEqual(self.webhook_1.main_queue.size(), 1)
        message = json.loads(self.webhook_1.main_queue.dequeue())
        self.assertNotIn("username", message)
        self.assertNotIn("avatar_url", message)
        self.assertIn("My Tracker", message["content"])

    def test_send_as_fleetkill(self):
        self.tracker.identify_fleets = True
        self.tracker.save()
        killmail = self.tracker.process_killmail(load_killmail(10000101))

        self.tracker.generate_killmail_message(Killmail.from_json(killmail.asjson()))

        self.assertEqual(self.webhook_1.main_queue.size(), 1)
        message = json.loads(self.webhook_1.main_queue.dequeue())
        self.assertIn("| Fleetkill", message["embeds"][0]["title"])

    def test_can_add_intro_text(self):
        killmail = self.tracker.process_killmail(load_killmail(10000101))

        self.tracker.generate_killmail_message(killmail, intro_text="Intro Text")

        self.assertEqual(self.webhook_1.main_queue.size(), 1)
        message = json.loads(self.webhook_1.main_queue.dequeue())
        self.assertIn("Intro Text", message["content"])

    def test_without_tracker_info(self):
        killmail = load_killmail(10000001)

        self.tracker.generate_killmail_message(Killmail.from_json(killmail.asjson()))

        self.assertEqual(self.webhook_1.main_queue.size(), 1)

    def test_can_ping_everybody(self):
        tracker = TrackerFactory(
            webhook=self.webhook_1, ping_type=Tracker.ChannelPingType.EVERYBODY
        )

        killmail = tracker.process_killmail(load_killmail(10000001))

        tracker.generate_killmail_message(Killmail.from_json(killmail.asjson()))

        self.assertEqual(self.webhook_1.main_queue.size(), 1)
        message = json.loads(self.webhook_1.main_queue.dequeue())
        self.assertIn("@everybody", message["content"])

    def test_can_ping_here(self):
        self.tracker.ping_type = Tracker.ChannelPingType.HERE
        self.tracker.save()

        killmail = self.tracker.process_killmail(load_killmail(10000001))

        self.tracker.generate_killmail_message(Killmail.from_json(killmail.asjson()))

        self.assertEqual(self.webhook_1.main_queue.size(), 1)
        message = json.loads(self.webhook_1.main_queue.dequeue())
        self.assertIn("@here", message["content"])

    def test_can_ping_nobody(self):
        self.tracker.ping_type = Tracker.ChannelPingType.NONE
        self.tracker.save()
        killmail = self.tracker.process_killmail(load_killmail(10000001))

        self.tracker.generate_killmail_message(Killmail.from_json(killmail.asjson()))

        self.assertEqual(self.webhook_1.main_queue.size(), 1)
        message = json.loads(self.webhook_1.main_queue.dequeue())
        self.assertNotIn("@everybody", message["content"])
        self.assertNotIn("@here", message["content"])

    def test_can_disable_posting_name(self):
        self.tracker.s_posting_name = False
        self.tracker.save()
        killmail = self.tracker.process_killmail(load_killmail(10000001))

        self.tracker.generate_killmail_message(Killmail.from_json(killmail.asjson()))

        self.assertEqual(self.webhook_1.main_queue.size(), 1)
        message = json.loads(self.webhook_1.main_queue.dequeue())
        self.assertNotIn("Ping Nobody", message["content"])

    def test_can_send_npc_killmail(self):
        killmail = self.tracker.process_killmail(load_killmail(10000301))

        self.tracker.generate_killmail_message(Killmail.from_json(killmail.asjson()))

        self.assertEqual(self.webhook_1.main_queue.size(), 1)

    def test_can_handle_victim_without_character(self):
        killmail = self.tracker.process_killmail(load_killmail(10000501))

        self.tracker.generate_killmail_message(Killmail.from_json(killmail.asjson()))

        self.assertEqual(self.webhook_1.main_queue.size(), 1)

    def test_can_handle_victim_without_corporation(self):
        killmail = self.tracker.process_killmail(load_killmail(10000502))

        self.tracker.generate_killmail_message(Killmail.from_json(killmail.asjson()))

        self.assertEqual(self.webhook_1.main_queue.size(), 1)

    def test_can_handle_final_attacker_with_no_character(self):
        killmail = self.tracker.process_killmail(load_killmail(10000503))

        self.tracker.generate_killmail_message(Killmail.from_json(killmail.asjson()))

        self.assertEqual(self.webhook_1.main_queue.size(), 1)

    def test_can_handle_matching_type_ids(self):
        svipul = EveType.objects.get(id=34562)
        self.tracker.require_attackers_ship_types.add(svipul)
        killmail = self.tracker.process_killmail(load_killmail(10000001))

        self.tracker.generate_killmail_message(Killmail.from_json(killmail.asjson()))

        self.assertEqual(self.webhook_1.main_queue.size(), 1)
