"""Fetching killmails from ZKB."""

# pylint: disable = redefined-builtin

import json
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime
from http import HTTPStatus
from typing import List, Optional, Set
from urllib.parse import quote_plus

import requests
from dacite import DaciteError, from_dict
from redis.exceptions import LockError
from simplejson.errors import JSONDecodeError

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.utils.dateparse import parse_datetime
from eveuniverse.models import EveType

from allianceauth.services.hooks import get_extension_logger
from app_utils.allianceauth import get_redis_client
from app_utils.json import JSONDateTimeDecoder, JSONDateTimeEncoder
from app_utils.logging import LoggerAddTag

from killtracker import USER_AGENT_TEXT, __title__
from killtracker.app_settings import (
    KILLTRACKER_QUEUE_ID,
    KILLTRACKER_REDISQ_LOCK_TIMEOUT,
    KILLTRACKER_REDISQ_TTW,
    KILLTRACKER_STORAGE_KILLMAILS_LIFETIME,
)
from killtracker.exceptions import KillmailDoesNotExist
from killtracker.providers import esi

logger = LoggerAddTag(get_extension_logger(__name__), __title__)

ZKB_REDISQ_URL = "https://redisq.zkillboard.com/listen.php"
ZKB_API_URL = "https://zkillboard.com/api/"
ZKB_KILLMAIL_BASEURL = "https://zkillboard.com/kill/"
REQUESTS_TIMEOUT = (5, 30)

MAIN_MINIMUM_COUNT = 2
MAIN_MINIMUM_SHARE = 0.25

# TODO: Factor out logic for accessing the API to another module


@dataclass
class _KillmailBase:
    """Base class for all Killmail."""

    def asdict(self) -> dict:
        """Return this object as dict."""
        return asdict(self)


@dataclass
class _KillmailCharacter(_KillmailBase):
    ENTITY_PROPS = [
        "character_id",
        "corporation_id",
        "alliance_id",
        "faction_id",
        "ship_type_id",
    ]

    character_id: Optional[int] = None
    corporation_id: Optional[int] = None
    alliance_id: Optional[int] = None
    faction_id: Optional[int] = None
    ship_type_id: Optional[int] = None


@dataclass
class KillmailVictim(_KillmailCharacter):
    """A victim on a killmail."""

    damage_taken: Optional[int] = None


@dataclass
class KillmailAttacker(_KillmailCharacter):
    """An attacker on a killmail."""

    ENTITY_PROPS = _KillmailCharacter.ENTITY_PROPS + ["weapon_type_id"]

    damage_done: Optional[int] = None
    is_final_blow: Optional[bool] = None
    security_status: Optional[float] = None
    weapon_type_id: Optional[int] = None


@dataclass
class KillmailPosition(_KillmailBase):
    "A position for a killmail."
    x: Optional[float] = None
    y: Optional[float] = None
    z: Optional[float] = None


@dataclass
class KillmailZkb(_KillmailBase):
    """A ZKB entry for a killmail."""

    location_id: Optional[int] = None
    hash: Optional[str] = None
    fitted_value: Optional[float] = None
    total_value: Optional[float] = None
    points: Optional[int] = None
    is_npc: Optional[bool] = None
    is_solo: Optional[bool] = None
    is_awox: Optional[bool] = None


@dataclass(eq=True, frozen=True)
class _EntityCount:
    """Counts of an Eve entity."""

    CATEGORY_ALLIANCE = "alliance"
    CATEGORY_CORPORATION = "corporation"
    CATEGORY_INVENTORY_GROUP = "inventory_group"

    id: int
    category: str
    name: Optional[str] = None
    count: Optional[int] = None

    @property
    def is_alliance(self) -> bool:
        """Return True when count is for an alliance."""
        return self.category == self.CATEGORY_ALLIANCE

    @property
    def is_corporation(self) -> bool:
        """Return True when count is for a corporation."""
        return self.category == self.CATEGORY_CORPORATION


@dataclass
class TrackerInfo(_KillmailBase):
    """A tracker info."""

    tracker_pk: int
    jumps: Optional[int] = None
    distance: Optional[float] = None
    main_org: Optional[_EntityCount] = None
    main_ship_group: Optional[_EntityCount] = None
    matching_ship_type_ids: Optional[List[int]] = None


@dataclass
class Killmail(_KillmailBase):
    """A killmail body."""

    _STORAGE_BASE_KEY = "killtracker_storage_killmail_"

    id: int
    time: datetime
    victim: KillmailVictim
    attackers: List[KillmailAttacker]
    position: KillmailPosition
    zkb: KillmailZkb
    solar_system_id: Optional[int] = None
    tracker_info: Optional[TrackerInfo] = None

    def __repr__(self):
        return f"{type(self).__name__}(id={self.id})"

    def attackers_distinct_alliance_ids(self) -> Set[int]:
        """Return distinct alliance IDs of all attackers."""
        return {obj.alliance_id for obj in self.attackers if obj.alliance_id}

    def attackers_distinct_corporation_ids(self) -> Set[int]:
        """Return distinct corporation IDs of all attackers."""
        return {obj.corporation_id for obj in self.attackers if obj.corporation_id}

    def attackers_distinct_character_ids(self) -> Set[int]:
        """Return distinct character IDs of all attackers."""
        return {obj.character_id for obj in self.attackers if obj.character_id}

    def attackers_ship_type_ids(self) -> List[int]:
        """Returns ship type IDs of all attackers with duplicates."""
        return [obj.ship_type_id for obj in self.attackers if obj.ship_type_id]

    def attackers_weapon_type_ids(self) -> List[int]:
        """Returns weapon type IDs of all attackers with duplicates."""
        return [obj.weapon_type_id for obj in self.attackers if obj.weapon_type_id]

    def entity_ids(self) -> Set[int]:
        """Return distinct IDs of all entities (excluding None)."""
        ids = {
            self.victim.character_id,
            self.victim.corporation_id,
            self.victim.alliance_id,
            self.victim.faction_id,
            self.victim.ship_type_id,
            self.solar_system_id,
        }
        for attacker in self.attackers:
            ids.update(
                {
                    attacker.character_id,
                    attacker.corporation_id,
                    attacker.alliance_id,
                    attacker.faction_id,
                    attacker.ship_type_id,
                    attacker.weapon_type_id,
                }
            )
        ids.discard(None)
        return ids  # type: ignore

    def ship_type_distinct_ids(self) -> Set[int]:
        """Return distinct ship type IDs of all entities that are not None."""
        ids = set(self.attackers_ship_type_ids())
        ship_type_id = self.victim.ship_type_id if self.victim else None
        if ship_type_id:
            ids.add(ship_type_id)
        return ids

    def attacker_final_blow(self) -> Optional[KillmailAttacker]:
        """Returns the attacker with the final blow or None if not found."""
        for attacker in self.attackers:
            if attacker.is_final_blow:
                return attacker
        return None

    def asjson(self) -> str:
        """Convert killmail into JSON data."""
        return json.dumps(asdict(self), cls=JSONDateTimeEncoder)

    def save(self) -> None:
        """Save this killmail to temporary storage."""
        cache.set(
            key=self._storage_key(self.id),
            value=self.asjson(),
            timeout=KILLTRACKER_STORAGE_KILLMAILS_LIFETIME,
        )

    def delete(self) -> None:
        """Delete this killmail from temporary storage."""
        cache.delete(self._storage_key(self.id))

    def clone_with_tracker_info(
        self,
        tracker_pk,
        jumps: Optional[int] = None,
        distance: Optional[float] = None,
        matching_ship_type_ids: Optional[List[int]] = None,
        minimum_count: int = MAIN_MINIMUM_COUNT,
        minimum_share: float = MAIN_MINIMUM_SHARE,
    ) -> "Killmail":
        """Clone this killmail and add tracker info."""
        main_ship_group = self._calc_main_attacker_ship_group(
            minimum_count, minimum_share
        )
        main_org = self._calc_main_attacker_org(minimum_count, minimum_share)
        killmail_new = deepcopy(self)
        killmail_new.tracker_info = TrackerInfo(
            tracker_pk=tracker_pk,
            jumps=jumps,
            distance=distance,
            main_org=main_org,
            main_ship_group=main_ship_group,
            matching_ship_type_ids=matching_ship_type_ids,
        )
        return killmail_new

    def _calc_main_attacker_ship_group(
        self,
        minimum_count: int,
        minimum_share: float,
    ) -> Optional[_EntityCount]:
        """Return the main attacker group with count."""

        ships_type_ids = self.attackers_ship_type_ids()
        ship_types = EveType.objects.filter(id__in=ships_type_ids).select_related(
            "eve_group"
        )
        ship_groups = []
        for ships_type_id in ships_type_ids:
            try:
                ship_type = ship_types.get(id=ships_type_id)
            except EveType.DoesNotExist:
                continue

            ship_groups.append(
                _EntityCount(
                    id=ship_type.eve_group_id,  # type: ignore
                    category=_EntityCount.CATEGORY_INVENTORY_GROUP,
                    name=ship_type.eve_group.name,
                )
            )

        if ship_groups:
            ship_groups_2 = [
                _EntityCount(
                    id=x.id,
                    category=x.category,
                    name=x.name,
                    count=ship_groups.count(x),
                )
                for x in set(ship_groups)
            ]
            max_count = max(x.count or 0 for x in ship_groups_2)
            threshold = max(len(self.attackers) * minimum_share, minimum_count)
            if max_count >= threshold:
                return sorted(ship_groups_2, key=lambda x: x.count or 0).pop()

        return None

    def _calc_main_attacker_org(
        self,
        minimum_count: int,
        minimum_share: float,
    ) -> Optional[_EntityCount]:
        """Return the main attacker group with count."""
        org_items = []
        for attacker in self.attackers:
            if attacker.alliance_id:
                org_items.append(
                    _EntityCount(
                        id=attacker.alliance_id, category=_EntityCount.CATEGORY_ALLIANCE
                    )
                )

            if attacker.corporation_id:
                org_items.append(
                    _EntityCount(
                        id=attacker.corporation_id,
                        category=_EntityCount.CATEGORY_CORPORATION,
                    )
                )

        if org_items:
            org_items_2 = [
                _EntityCount(
                    id=obj.id, category=obj.category, count=org_items.count(obj)
                )
                for obj in set(org_items)
            ]
            max_count = max(x.count or 0 for x in org_items_2)
            threshold = max(len(self.attackers) * minimum_share, minimum_count)
            if max_count >= threshold:
                org_items_3 = [x for x in org_items_2 if x.count == max_count]
                if len(org_items_3) > 1:
                    org_items_4 = [x for x in org_items_3 if x.is_alliance]
                    if len(org_items_4) > 0:
                        return org_items_4[0]

                return org_items_3[0]

        return None

    @classmethod
    def get(cls, id: int) -> "Killmail":
        """Fetch a killmail from temporary storage."""
        data = cache.get(key=cls._storage_key(id))
        if not data:
            raise KillmailDoesNotExist(
                f"Killmail with ID {id} does not exist in storage."
            )
        return cls.from_json(data)

    @classmethod
    def _storage_key(cls, id: int) -> str:
        return cls._STORAGE_BASE_KEY + str(id)

    @classmethod
    def from_dict(cls, data: dict) -> "Killmail":
        """Create new object from dictionary."""
        try:
            return from_dict(data_class=Killmail, data=data)
        except DaciteError as ex:
            logger.error("Failed to convert dict to %s", type(cls), exc_info=True)
            raise ex

    @classmethod
    def from_json(cls, json_str: str) -> "Killmail":
        """Create new object from JSON data."""
        return cls.from_dict(json.loads(json_str, cls=JSONDateTimeDecoder))

    @classmethod
    def create_from_zkb_redisq(cls) -> Optional["Killmail"]:
        """Fetches and returns a killmail from ZKB.

        Returns None if no killmail is received.
        """
        if not KILLTRACKER_QUEUE_ID:
            raise ImproperlyConfigured(
                "You need to define a queue ID in your settings."
            )

        if "," in KILLTRACKER_QUEUE_ID:
            raise ImproperlyConfigured("A queue ID must not contains commas.")

        redis = get_redis_client()
        params = {
            "queueID": quote_plus(KILLTRACKER_QUEUE_ID),
            "ttw": KILLTRACKER_REDISQ_TTW,
        }
        try:
            logger.info("Trying to fetch killmail from ZKB RedisQ...")
            with redis.lock(
                cls.lock_key(), blocking_timeout=KILLTRACKER_REDISQ_LOCK_TIMEOUT
            ):
                response = requests.get(
                    ZKB_REDISQ_URL,
                    params=params,
                    timeout=REQUESTS_TIMEOUT,
                    headers={"User-Agent": USER_AGENT_TEXT},
                )
        except LockError:
            logger.warning(
                "Failed to acquire lock for atomic access to RedisQ.",
                exc_info=settings.DEBUG,  # provide details in DEBUG mode
            )
            return None

        if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
            logger.error("429 Client Error: Too many requests: %s", response.text)
            return None

        response.raise_for_status()

        try:
            data = response.json()
        except JSONDecodeError:
            logger.error("Error from ZKB API:\n%s", response.text)
            return None

        if data:
            logger.debug("data:\n%s", data)

        if data and "package" in data and data["package"]:
            logger.info("Received a killmail from ZKB RedisQ")
            package_data = data["package"]
            return cls._create_from_dict(package_data)

        logger.debug("Did not received a killmail from ZKB RedisQ")
        return None

    @classmethod
    def create_from_zkb_api(cls, killmail_id: int) -> Optional["Killmail"]:
        """Fetches and returns a killmail from ZKB API.

        results are cached
        """
        cache_key = f"{__title__.upper()}_KILLMAIL_{killmail_id}"
        killmail_json = cache.get(cache_key)
        if killmail_json:
            return Killmail.from_json(killmail_json)

        logger.info(
            "Trying to fetch killmail from ZKB API with killmail ID %d ...",
            killmail_id,
        )
        url = f"{ZKB_API_URL}killID/{killmail_id}/"
        response = requests.get(
            url, timeout=REQUESTS_TIMEOUT, headers={"User-Agent": USER_AGENT_TEXT}
        )
        response.raise_for_status()
        zkb_data = response.json()
        if not zkb_data:
            logger.warning(
                "ZKB API did not return any data for killmail ID %d", killmail_id
            )
            return None

        logger.debug("data:\n%s", zkb_data)
        try:
            killmail_zkb = zkb_data[0]
        except KeyError:
            return None

        killmail_esi = esi.client.Killmails.get_killmails_killmail_id_killmail_hash(
            killmail_id=killmail_id, killmail_hash=killmail_zkb["zkb"]["hash"]
        ).results()
        if not killmail_esi:
            logger.warning(
                "ESI did not return any data for killmail ID %d", killmail_id
            )
            return None

        # esi returns datetime, but _create_from_dict() expects a string in
        # same format as returned from zkb redisq
        killmail_esi["killmail_time"] = killmail_esi["killmail_time"].strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

        killmail_dict = {
            "killID": killmail_id,
            "killmail": killmail_esi,
            "zkb": killmail_zkb["zkb"],
        }
        killmail = cls._create_from_dict(killmail_dict)
        if killmail:
            cache.set(key=cache_key, value=killmail.asjson())
        return killmail

    @classmethod
    def _create_from_dict(cls, package_data: dict) -> Optional["Killmail"]:
        """creates a new object from given dict.
        Needs to confirm with data structure returned from ZKB RedisQ
        """

        killmail = None
        if "killmail" in package_data:
            killmail_data = package_data["killmail"]
            victim, position = cls._extract_victim_and_position(killmail_data)
            attackers = cls._extract_attackers(killmail_data)
            zkb = cls._extract_zkb(package_data)

            params = {
                "id": killmail_data["killmail_id"],
                "time": parse_datetime(killmail_data["killmail_time"]),
                "victim": victim,
                "position": position,
                "attackers": attackers,
                "zkb": zkb,
            }
            if "solar_system_id" in killmail_data:
                params["solar_system_id"] = killmail_data["solar_system_id"]

            killmail = Killmail(**params)

        return killmail

    @classmethod
    def _extract_victim_and_position(cls, killmail_data: dict):
        victim = KillmailVictim()
        position = KillmailPosition()
        if "victim" in killmail_data:
            victim_data = killmail_data["victim"]
            params = {}
            for prop in KillmailVictim.ENTITY_PROPS + ["damage_taken"]:
                if prop in victim_data:
                    params[prop] = victim_data[prop]

            victim = KillmailVictim(**params)

            if "position" in victim_data:
                position_data = victim_data["position"]
                params = {}
                for prop in ["x", "y", "z"]:
                    if prop in position_data:
                        params[prop] = position_data[prop]

                position = KillmailPosition(**params)

        return victim, position

    @classmethod
    def _extract_attackers(cls, killmail_data: dict) -> List[KillmailAttacker]:
        attackers = []
        for attacker_data in killmail_data.get("attackers", []):
            params = {}
            for prop in KillmailAttacker.ENTITY_PROPS + [
                "damage_done",
                "security_status",
            ]:
                if prop in attacker_data:
                    params[prop] = attacker_data[prop]

            if "final_blow" in attacker_data:
                params["is_final_blow"] = attacker_data["final_blow"]

            attackers.append(KillmailAttacker(**params))
        return attackers

    @classmethod
    def _extract_zkb(cls, package_data):
        if "zkb" not in package_data:
            return KillmailZkb()

        zkb_data = package_data["zkb"]
        params = {}
        for prop, mapping in (
            ("locationID", "location_id"),
            ("hash", None),
            ("fittedValue", "fitted_value"),
            ("totalValue", "total_value"),
            ("points", None),
            ("npc", "is_npc"),
            ("solo", "is_solo"),
            ("awox", "is_awox"),
        ):
            if prop in zkb_data:
                if mapping:
                    params[mapping] = zkb_data[prop]
                else:
                    params[prop] = zkb_data[prop]

        return KillmailZkb(**params)

    @staticmethod
    def lock_key() -> str:
        """Key used for lock operation on Redis."""
        return f"{__title__.upper()}_REDISQ_LOCK"

    @classmethod
    def reset_lock_key(cls):
        """Delete lock key if it exists.

        It can happen that a lock key is not cleaned up
        and then prevents this class from ever acquiring a lock again.
        To prevent this we are deleting the lock key at system start.
        """
        redis = get_redis_client()
        if redis.delete(cls.lock_key()) > 0:
            logger.warning("A stuck lock key was cleared.")
