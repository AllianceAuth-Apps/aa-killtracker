import json
from datetime import timedelta
from typing import List, Set
from unittest.mock import Mock, PropertyMock, patch

from django.test import TestCase
from django.utils.timezone import now
from eveuniverse.models import EveSolarSystem
from eveuniverse.tests.testdata.factories_2 import (
    EveConstellationFactory,
    EveGroupFactory,
    EveRegionFactory,
    EveSolarSystemFactory,
    EveTypeFactory,
)

from allianceauth.eveonline.models import EveCharacter
from allianceauth.tests.auth_utils import AuthUtils
from app_utils.testdata_factories import (
    EveAllianceInfoFactory,
    EveCorporationInfoFactory,
    UserMainFactory,
)
from app_utils.testing import NoSocketsTestCase

from killtracker.core.zkb import Killmail, _EntityCount
from killtracker.models import Tracker
from killtracker.tests.testdata.factories import (
    EveEntityAllianceFactory,
    EveEntityInventoryTypeFactory,
    EveFactionInfoFactory,
    EveSolarSystemHighSecFactory,
    EveSolarSystemLowSecFactory,
    EveSolarSystemNullSecFactory,
    EveSolarSystemWSpaceFactory,
    KillmailAttackerFactory,
    KillmailFactory,
    KillmailVictimFactory,
    TrackerFactory,
    WebhookFactory,
)

MODELS_PATH = "killtracker.models"


def _process_killmails(tracker: Tracker, killmails: List[Killmail]) -> List[Killmail]:
    result = []
    for km in killmails:
        km_2 = tracker.process_killmail(km)
        if km_2:
            result.append(km_2)
    return result


def _killmail_ids(killmails: List[Killmail]) -> Set[int]:
    return {x.id for x in killmails}


class TestTracker_ProcessKillmail_Misc(NoSocketsTestCase):
    def test_can_match_all(self):
        # given
        km1 = KillmailFactory()
        km2 = KillmailFactory()
        tracker = TrackerFactory()

        # when
        got = _killmail_ids(_process_killmails(tracker, [km1, km2]))

        # then
        want = {km1.id, km2.id}
        self.assertSetEqual(got, want)

    @patch(MODELS_PATH + ".trackers.KILLTRACKER_KILLMAIL_MAX_AGE_FOR_TRACKER", 60)
    def test_excludes_older_killmails(self):
        km1 = KillmailFactory()
        km2 = KillmailFactory(time=now() - timedelta(hours=2))
        tracker = TrackerFactory()

        # when
        result = _process_killmails(tracker, [km1, km2])

        # then
        got = _killmail_ids(result)
        want = {km1.id}
        self.assertSetEqual(got, want)

    def test_can_process_killmail_without_solar_system(self):
        # given
        km = KillmailFactory(solar_system_id=None)
        tracker = TrackerFactory()

        # when
        got = tracker.process_killmail(km)

        # then
        self.assertIsNotNone(got)

    def test_can_filter_min_attackers(self):
        km1 = KillmailFactory(attacker_count=5)
        km2 = KillmailFactory(attacker_count=1)
        tracker = TrackerFactory(require_min_attackers=3)

        # when
        result = _process_killmails(tracker, [km1, km2])

        # then
        got = _killmail_ids(result)
        want = {km1.id}
        self.assertSetEqual(got, want)

    def test_can_filter_max_attackers(self):
        km1 = KillmailFactory(attacker_count=2)
        km2 = KillmailFactory(attacker_count=5)
        tracker = TrackerFactory(require_max_attackers=3)

        # when
        result = _process_killmails(tracker, [km1, km2])

        # then
        got = _killmail_ids(result)
        want = {km1.id}
        self.assertSetEqual(got, want)

    def test_should_deny_when_value_is_below_minimum(self):
        killmail = KillmailFactory(zkb__total_value=50_000_000)
        tracker = TrackerFactory(require_min_value=51)
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNone(result)

    def test_should_threat_no_value_as_zero(self):
        killmail = KillmailFactory(zkb__total_value=None)
        tracker = TrackerFactory(require_min_value=51)
        # when
        result = tracker.process_killmail(killmail)
        # then
        self.assertIsNone(result)

    def test_can_exclude_npc_kills(self):
        km1 = KillmailFactory()
        km2 = KillmailFactory(is_npc=True)
        tracker = TrackerFactory(exclude_npc_kills=True)

        # when
        result = _process_killmails(tracker, [km1, km2])

        # then
        got = _killmail_ids(result)
        want = {km1.id}
        self.assertSetEqual(got, want)

    def test_can_require_npc_kills(self):
        km1 = KillmailFactory(is_npc=True)
        km2 = KillmailFactory()
        tracker = TrackerFactory(require_npc_kills=True)

        # when
        result = _process_killmails(tracker, [km1, km2])

        # then
        got = _killmail_ids(result)
        want = {km1.id}
        self.assertSetEqual(got, want)


class TestTracker_ProcessKillmail_WarKills(NoSocketsTestCase):
    def test_can_exclude_war_kills(self):
        km1 = KillmailFactory(war_id=None)
        km2 = KillmailFactory(war_id=99)
        tracker = TrackerFactory(exclude_war_kills=True)

        # when
        result = _process_killmails(tracker, [km1, km2])

        # then
        got = _killmail_ids(result)
        want = {km1.id}
        self.assertSetEqual(got, want)

    def test_can_require_war_kills(self):
        km1 = KillmailFactory(war_id=99)
        km2 = KillmailFactory(war_id=None)
        tracker = TrackerFactory(require_war_kills=True)

        # when
        result = _process_killmails(tracker, [km1, km2])

        # then
        got = _killmail_ids(result)
        want = {km1.id}
        self.assertSetEqual(got, want)


@patch(MODELS_PATH + ".trackers.Tracker._calc_distances")
class TestTracker_ProcessKillmail_Distances(NoSocketsTestCase):
    def test_can_filter_max_jumps(self, mock_calc_distances: Mock):
        km1 = KillmailFactory()
        km2 = KillmailFactory()
        tracker = TrackerFactory(require_max_jumps=3)

        def calc_distances(solar_system: EveSolarSystem):
            match solar_system.id:
                case km1.solar_system_id:
                    return 1, 0
                case km2.solar_system_id:
                    return 99, 0

            raise RuntimeError(f"Not found: {solar_system.id}")

        mock_calc_distances.side_effect = calc_distances

        # when
        result = _process_killmails(tracker, [km1, km2])

        # then
        got = _killmail_ids(result)
        want = {km1.id}
        self.assertSetEqual(got, want)

    def test_can_filter_max_distance(self, mock_calc_distances: Mock):
        km1 = KillmailFactory()
        km2 = KillmailFactory()
        tracker = TrackerFactory(require_max_distance=3)

        def calc_distances(solar_system: EveSolarSystem):
            match solar_system.id:
                case km1.solar_system_id:
                    return 0, 1
                case km2.solar_system_id:
                    return 0, 99

            raise RuntimeError(f"Not found: {solar_system.id}")

        mock_calc_distances.side_effect = calc_distances

        # when
        result = _process_killmails(tracker, [km1, km2])

        # then
        got = _killmail_ids(result)
        want = {km1.id}
        self.assertSetEqual(got, want)


class TestTracker_ProcessKillmail_Types(NoSocketsTestCase):
    def test_can_require_attackers_ship_groups(self):
        km1 = KillmailFactory(attacker_count=1)
        km2 = KillmailFactory(attacker_count=1)
        tracker = TrackerFactory()
        EveTypeFactory(id=km1.victim.ship_type_id)
        et = EveTypeFactory(id=km1.attackers[0].ship_type_id)
        EveTypeFactory(id=km2.victim.ship_type_id)
        EveTypeFactory(id=km2.attackers[0].ship_type_id)
        tracker.require_attackers_ship_groups.add(et.eve_group)

        # when
        result = _process_killmails(tracker, [km1, km2])

        # then
        got = _killmail_ids(result)
        want = {km1.id}
        self.assertSetEqual(got, want)
        self.assertEqual(result[0].tracker_info.matching_ship_type_ids, [et.id])

    def test_can_require_attackers_ship_types(self):
        km1 = KillmailFactory(attacker_count=1)
        km2 = KillmailFactory(attacker_count=1)
        tracker = TrackerFactory()
        EveTypeFactory(id=km1.victim.ship_type_id)
        et = EveTypeFactory(id=km1.attackers[0].ship_type_id)
        EveTypeFactory(id=km2.victim.ship_type_id)
        EveTypeFactory(id=km2.attackers[0].ship_type_id)
        tracker.require_attackers_ship_types.add(et)

        # when
        result = _process_killmails(tracker, [km1, km2])

        # then
        got = _killmail_ids(result)
        want = {km1.id}
        self.assertSetEqual(got, want)
        self.assertEqual(result[0].tracker_info.matching_ship_type_ids, [et.id])

    def test_can_require_victim_ship_group(self):
        km1 = KillmailFactory(attacker_count=1)
        km2 = KillmailFactory(attacker_count=1)
        tracker = TrackerFactory()
        et = EveTypeFactory(id=km1.victim.ship_type_id)
        EveTypeFactory(id=km1.attackers[0].ship_type_id)
        EveTypeFactory(id=km2.victim.ship_type_id)
        EveTypeFactory(id=km2.attackers[0].ship_type_id)
        tracker.require_victim_ship_groups.add(et.eve_group)

        # when
        result = _process_killmails(tracker, [km1, km2])

        # then
        got = _killmail_ids(result)
        want = {km1.id}
        self.assertSetEqual(got, want)
        self.assertEqual(result[0].tracker_info.matching_ship_type_ids, [et.id])

    def test_can_require_victim_ship_types(self):
        km1 = KillmailFactory(attacker_count=1)
        km2 = KillmailFactory(attacker_count=1)
        tracker = TrackerFactory()
        et = EveTypeFactory(id=km1.victim.ship_type_id)
        EveTypeFactory(id=km1.attackers[0].ship_type_id)
        EveTypeFactory(id=km2.victim.ship_type_id)
        EveTypeFactory(id=km2.attackers[0].ship_type_id)
        tracker.require_victim_ship_types.add(et)

        # when
        result = _process_killmails(tracker, [km1, km2])

        # then
        got = _killmail_ids(result)
        want = {km1.id}
        self.assertSetEqual(got, want)
        self.assertEqual(result[0].tracker_info.matching_ship_type_ids, [et.id])

    def test_can_require_attackers_weapon_groups(self):
        km1 = KillmailFactory(attacker_count=1)
        km2 = KillmailFactory(attacker_count=1)
        tracker = TrackerFactory()
        et = EveTypeFactory(id=km1.attackers[0].weapon_type_id)
        EveTypeFactory(id=km2.attackers[0].weapon_type_id)
        tracker.require_attackers_weapon_groups.add(et.eve_group)

        # when
        result = _process_killmails(tracker, [km1, km2])

        # then
        got = _killmail_ids(result)
        want = {km1.id}
        self.assertSetEqual(got, want)

    def test_can_require_attackers_weapon_types(self):
        km1 = KillmailFactory(attacker_count=1)
        km2 = KillmailFactory(attacker_count=1)
        tracker = TrackerFactory()
        et = EveTypeFactory(id=km1.attackers[0].weapon_type_id)
        EveTypeFactory(id=km2.attackers[0].weapon_type_id)
        tracker.require_attackers_weapon_types.add(et)

        # when
        result = _process_killmails(tracker, [km1, km2])

        # then
        got = _killmail_ids(result)
        want = {km1.id}
        self.assertSetEqual(got, want)


class TestTracker_ProcessKillmail_Map(NoSocketsTestCase):
    def test_can_filter_high_sec_kills(self):
        km1 = KillmailFactory(solar_system_id=EveSolarSystemLowSecFactory().id)
        km2 = KillmailFactory(solar_system_id=EveSolarSystemHighSecFactory().id)
        tracker = TrackerFactory(exclude_high_sec=True)

        # when
        result = _process_killmails(tracker, [km1, km2])

        # then
        got = _killmail_ids(result)
        want = {km1.id}
        self.assertSetEqual(got, want)

    def test_can_filter_low_sec_kills(self):
        km1 = KillmailFactory(solar_system_id=EveSolarSystemHighSecFactory().id)
        km2 = KillmailFactory(solar_system_id=EveSolarSystemLowSecFactory().id)
        tracker = TrackerFactory(exclude_low_sec=True)

        # when
        result = _process_killmails(tracker, [km1, km2])

        # then
        got = _killmail_ids(result)
        want = {km1.id}
        self.assertSetEqual(got, want)

    def test_can_filter_null_sec_kills(self):
        km1 = KillmailFactory(solar_system_id=EveSolarSystemHighSecFactory().id)
        km2 = KillmailFactory(solar_system_id=EveSolarSystemNullSecFactory().id)
        tracker = TrackerFactory(exclude_null_sec=True)

        # when
        result = _process_killmails(tracker, [km1, km2])

        # then
        got = _killmail_ids(result)
        want = {km1.id}
        self.assertSetEqual(got, want)

    def test_can_filter_w_space_kills(self):
        km1 = KillmailFactory(solar_system_id=EveSolarSystemHighSecFactory().id)
        km2 = KillmailFactory(solar_system_id=EveSolarSystemWSpaceFactory().id)
        tracker = TrackerFactory(exclude_w_space=True)

        # when
        result = _process_killmails(tracker, [km1, km2])

        # then
        got = _killmail_ids(result)
        want = {km1.id}
        self.assertSetEqual(got, want)

    def test_can_require_region(self):
        km1 = KillmailFactory()
        km2 = KillmailFactory()
        tracker = TrackerFactory()
        ess = EveSolarSystem.objects.get(id=km1.solar_system_id)
        tracker.require_regions.add(ess.eve_constellation.eve_region)

        # when
        result = _process_killmails(tracker, [km1, km2])

        # then
        got = _killmail_ids(result)
        want = {km1.id}
        self.assertSetEqual(got, want)

    def test_can_require_constellation(self):
        km1 = KillmailFactory()
        km2 = KillmailFactory()
        tracker = TrackerFactory()
        ess = EveSolarSystem.objects.get(id=km1.solar_system_id)
        tracker.require_constellations.add(ess.eve_constellation)

        # when
        result = _process_killmails(tracker, [km1, km2])

        # then
        got = _killmail_ids(result)
        want = {km1.id}
        self.assertSetEqual(got, want)

    def test_can_require_solar_system(self):
        km1 = KillmailFactory()
        km2 = KillmailFactory()
        tracker = TrackerFactory()
        ess = EveSolarSystem.objects.get(id=km1.solar_system_id)
        tracker.require_solar_systems.add(ess)

        # when
        result = _process_killmails(tracker, [km1, km2])

        # then
        got = _killmail_ids(result)
        want = {km1.id}
        self.assertSetEqual(got, want)


class TestTracker_ProcessKillmail_State(NoSocketsTestCase):
    def test_should_require_attackers_states(self):
        user = UserMainFactory()
        main: EveCharacter = user.profile.main_character
        corporation = EveCorporationInfoFactory(corporation_id=main.corporation_id)
        my_state = AuthUtils.create_state(
            "dummy", member_corporations=corporation, priority=500
        )
        attacker = KillmailAttackerFactory(character_id=main.character_id)
        km1 = KillmailFactory(attackers=[attacker])

        km2 = KillmailFactory(attacker_count=1)

        tracker = TrackerFactory()
        tracker.require_attacker_states.add(my_state)

        # when
        result = _process_killmails(tracker, [km1, km2])

        # then
        got = _killmail_ids(result)
        want = {km1.id}
        self.assertSetEqual(got, want)

    def test_should_exclude_attacker_states(self):
        km1 = KillmailFactory(attacker_count=1)

        user = UserMainFactory()
        main: EveCharacter = user.profile.main_character
        corporation = EveCorporationInfoFactory(corporation_id=main.corporation_id)
        my_state = AuthUtils.create_state(
            "dummy", member_corporations=corporation, priority=500
        )
        attacker = KillmailAttackerFactory(character_id=main.character_id)
        km2 = KillmailFactory(attackers=[attacker])

        tracker = TrackerFactory()
        tracker.exclude_attacker_states.add(my_state)

        # when
        result = _process_killmails(tracker, [km1, km2])

        # then
        got = _killmail_ids(result)
        want = {km1.id}
        self.assertSetEqual(got, want)

    def test_should_require_victim_states(self):
        user = UserMainFactory()
        main: EveCharacter = user.profile.main_character
        corporation = EveCorporationInfoFactory(corporation_id=main.corporation_id)
        my_state = AuthUtils.create_state(
            "dummy", member_corporations=corporation, priority=500
        )
        victim = KillmailVictimFactory(character_id=main.character_id)
        km1 = KillmailFactory(victim=victim, attacker_count=1)

        km2 = KillmailFactory(attacker_count=1)

        tracker = TrackerFactory()
        tracker.require_victim_states.add(my_state)

        # when
        result = _process_killmails(tracker, [km1, km2])

        # then
        got = _killmail_ids(result)
        want = {km1.id}
        self.assertSetEqual(got, want)

    def test_should_exclude_victim_states(self):
        km1 = KillmailFactory(attacker_count=1)

        user = UserMainFactory()
        main: EveCharacter = user.profile.main_character
        corporation = EveCorporationInfoFactory(corporation_id=main.corporation_id)
        my_state = AuthUtils.create_state(
            "dummy", member_corporations=corporation, priority=500
        )
        victim = KillmailVictimFactory(character_id=main.character_id)
        km2 = KillmailFactory(victim=victim, attacker_count=1)

        tracker = TrackerFactory()
        tracker.exclude_victim_states.add(my_state)

        # when
        result = _process_killmails(tracker, [km1, km2])

        # then
        got = _killmail_ids(result)
        want = {km1.id}
        self.assertSetEqual(got, want)


class TestTracker_ProcessKillmail_Alliances(NoSocketsTestCase):
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


class TestTracker_ProcessKillmail_Corporations(NoSocketsTestCase):
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


class TestTracker_ProcessKillmail_Factions(NoSocketsTestCase):
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


@patch(MODELS_PATH + ".trackers.Tracker._calc_distances")
class TestTracker_ProcessKillmail_TrackerInfo(NoSocketsTestCase):
    def test_can_compile_basic_infos(self, mock_calc_distances: Mock):
        # given
        alliance = EveEntityAllianceFactory()
        ship_type_entity = EveEntityInventoryTypeFactory()
        ship_type = EveTypeFactory(id=ship_type_entity.id, eve_group__name="Alpha")
        km_1 = KillmailFactory(
            attackers=[
                KillmailAttackerFactory(
                    alliance_id=alliance.id, ship_type_id=ship_type_entity.id
                ),
                KillmailAttackerFactory(
                    alliance_id=alliance.id, ship_type_id=ship_type_entity.id
                ),
                KillmailAttackerFactory(alliance_id=alliance.id),
            ]
        )

        def calc_distances(solar_system: EveSolarSystem):
            match solar_system.id:
                case km_1.solar_system_id:
                    return 7, 5.5

            raise RuntimeError(f"Not found: {solar_system.id}")

        mock_calc_distances.side_effect = calc_distances

        origin = EveSolarSystemLowSecFactory()
        tracker = TrackerFactory(origin_solar_system_id=origin.id)

        # when
        km_2 = tracker.process_killmail(km_1)

        # then
        self.assertTrue(km_2.tracker_info)
        self.assertEqual(km_2.tracker_info.tracker_pk, tracker.pk)
        self.assertEqual(km_2.tracker_info.jumps, 7)
        self.assertEqual(km_2.tracker_info.distance, 5.5)
        self.assertEqual(
            km_2.tracker_info.main_org,
            _EntityCount(
                id=alliance.id,
                category=_EntityCount.CATEGORY_ALLIANCE,
                count=3,
            ),
        )
        self.assertEqual(
            km_2.tracker_info.main_ship_group,
            _EntityCount(
                id=ship_type.eve_group.id,
                category=_EntityCount.CATEGORY_INVENTORY_GROUP,
                count=2,
                name="Alpha",
            ),
        )


class TestTracker_EnqueueKillmail(NoSocketsTestCase):
    @patch(MODELS_PATH + ".webhooks.KILLTRACKER_WEBHOOK_SET_AVATAR", True)
    def test_can_enqueue_killmail_message(self):
        # given
        ship_type = EveTypeFactory()
        EveEntityInventoryTypeFactory(id=ship_type.id)
        km_1 = KillmailFactory(
            attackers=[
                KillmailAttackerFactory(ship_type_id=ship_type.id),
                KillmailAttackerFactory(ship_type_id=ship_type.id),
                KillmailAttackerFactory(),
            ]
        )
        EveTypeFactory(id=km_1.victim.ship_type_id)
        EveTypeFactory(id=km_1.attackers[2].ship_type_id)
        tracker = TrackerFactory(name="My Tracker")
        tracker.require_attackers_ship_types.add(ship_type)
        km_2 = tracker.process_killmail(km_1)

        # when
        tracker.generate_killmail_message(km_2)

        # then
        self.assertEqual(tracker.webhook._main_queue.size(), 1)
        message = json.loads(tracker.webhook._main_queue.dequeue())

        self.assertEqual(message["username"], "Killtracker")
        self.assertIsNotNone(message["avatar_url"])
        self.assertIn("My Tracker", message["content"])
        embed = message["embeds"][0]
        self.assertIn("| Killmail", embed["title"])
        self.assertIn(ship_type.eve_group.name, embed["description"])
        self.assertIn("Tracked ship types", embed["description"])

    @patch(MODELS_PATH + ".webhooks.KILLTRACKER_WEBHOOK_SET_AVATAR", False)
    def test_disabled_avatar(self):
        # given
        km_1 = KillmailFactory()
        tracker = TrackerFactory(name="My Tracker")
        km_2 = tracker.process_killmail(km_1)

        # when
        tracker.generate_killmail_message(km_2)

        # then
        self.assertEqual(tracker.webhook._main_queue.size(), 1)
        message = json.loads(tracker.webhook._main_queue.dequeue())
        self.assertNotIn("username", message)
        self.assertNotIn("avatar_url", message)
        self.assertIn("My Tracker", message["content"])


class TestTracker_HasLocalizationClause(NoSocketsTestCase):
    def test_has_localization_filter_1(self):
        tracker: Tracker = TrackerFactory.build(exclude_high_sec=True)
        self.assertTrue(tracker.has_localization_clause)

        tracker: Tracker = TrackerFactory.build(exclude_low_sec=True)
        self.assertTrue(tracker.has_localization_clause)

        tracker: Tracker = TrackerFactory.build(exclude_null_sec=True)
        self.assertTrue(tracker.has_localization_clause)

        tracker: Tracker = TrackerFactory.build(exclude_w_space=True)
        self.assertTrue(tracker.has_localization_clause)

        tracker = TrackerFactory.build(require_max_distance=10)
        self.assertTrue(tracker.has_localization_clause)

        tracker: Tracker = TrackerFactory.build(require_max_jumps=10)
        self.assertTrue(tracker.has_localization_clause)

    def test_has_no_matching_clause(self):
        tracker = TrackerFactory()
        self.assertFalse(tracker.has_localization_clause)

    def test_has_localization_filter_3(self):
        tracker = TrackerFactory()
        tracker.require_regions.add(EveRegionFactory())
        self.assertTrue(tracker.has_localization_clause)

    def test_has_localization_filter_4(self):
        tracker = TrackerFactory()
        tracker.require_constellations.add(EveConstellationFactory())
        self.assertTrue(tracker.has_localization_clause)

    def test_has_localization_filter_5(self):
        tracker = TrackerFactory()
        tracker.require_solar_systems.add(EveSolarSystemFactory())
        self.assertTrue(tracker.has_localization_clause)


class TestTracker_HasTypeClause(NoSocketsTestCase):
    def test_has_no_matching_clause(self):
        tracker = TrackerFactory()
        self.assertFalse(tracker.has_type_clause)

    def test_has_require_attackers_ship_groups(self):
        tracker = TrackerFactory()
        tracker.require_attackers_ship_groups.add(EveGroupFactory())
        self.assertTrue(tracker.has_type_clause)

    def test_has_require_attackers_ship_types(self):
        tracker = TrackerFactory()
        tracker.require_attackers_ship_types.add(EveTypeFactory())
        self.assertTrue(tracker.has_type_clause)

    def test_has_require_victim_ship_groups(self):
        tracker = TrackerFactory()
        tracker.require_victim_ship_groups.add(EveGroupFactory())
        self.assertTrue(tracker.has_type_clause)

    def test_has_require_victim_ship_types(self):
        tracker = TrackerFactory()
        tracker.require_victim_ship_types.add(EveTypeFactory())
        self.assertTrue(tracker.has_type_clause)


class TestTracker_SaveMethod(NoSocketsTestCase):
    def test_black_color_is_none(self):
        tracker = TrackerFactory(color="#000000")
        tracker.refresh_from_db()
        self.assertFalse(tracker.color)


class TestCalcDistance(TestCase):
    def test_should_return_distances_when_origin_exists(self):
        # given
        tracker = TrackerFactory()
        dest = EveSolarSystemFactory()

        # when
        with patch.object(
            Tracker, "origin_solar_system", new_callable=PropertyMock
        ) as m:
            m.return_value.jumps_to.return_value = 1
            m.return_value.distance_to.return_value = 1.2 * 9_460_000_000_000_000

            got = tracker._calc_distances(dest)

        # then
        self.assertEqual(got, (1, 1.2))

    def test_should_return_none_for_both_when_origin_not_exists(self):
        # given
        tracker = TrackerFactory()
        dest = EveSolarSystemFactory()

        # when
        got = tracker._calc_distances(dest)

        # then
        self.assertEqual(got, (None, None))

    def test_should_return_none_for_jumps_when_jumps_raises_exception(self):
        # given
        tracker = TrackerFactory()
        dest = EveSolarSystemFactory()

        # when
        with patch.object(
            Tracker, "origin_solar_system", new_callable=PropertyMock
        ) as m:
            m.return_value.jumps_to.side_effect = RuntimeError
            m.return_value.distance_to.return_value = 1.2 * 9_460_000_000_000_000

            got = tracker._calc_distances(dest)

        # then
        self.assertEqual(got, (None, 1.2))


# ------
