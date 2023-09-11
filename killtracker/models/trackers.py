"""Tracker models for killtracker."""

import json
from datetime import timedelta
from typing import List, Optional, Tuple

import dhooks_lite
from simple_mq import SimpleMQ

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.db import models
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _
from eveuniverse.helpers import meters_to_ly
from eveuniverse.models import (
    EveConstellation,
    EveGroup,
    EveRegion,
    EveSolarSystem,
    EveType,
)

from allianceauth.authentication.models import State
from allianceauth.eveonline.models import EveAllianceInfo, EveCorporationInfo
from allianceauth.services.hooks import get_extension_logger
from app_utils.allianceauth import get_redis_client
from app_utils.json import JSONDateTimeDecoder, JSONDateTimeEncoder
from app_utils.logging import LoggerAddTag
from app_utils.urls import static_file_absolute_url

from killtracker import APP_NAME, HOMEPAGE_URL, __title__, __version__
from killtracker.app_settings import (
    KILLTRACKER_KILLMAIL_MAX_AGE_FOR_TRACKER,
    KILLTRACKER_WEBHOOK_SET_AVATAR,
)
from killtracker.core.killmails import Killmail
from killtracker.exceptions import WebhookTooManyRequests
from killtracker.managers import EveTypePlusManager, TrackerManager, WebhookManager

logger = LoggerAddTag(get_extension_logger(__name__), __title__)


class EveTypePlus(EveType):
    """Variant to show group names with default output."""

    class Meta:
        proxy = True

    objects = EveTypePlusManager()

    def __str__(self) -> str:
        return f"{self.name} ({self.eve_group})"


class Webhook(models.Model):
    """A webhook to receive messages"""

    HTTP_TOO_MANY_REQUESTS = 429

    class WebhookType(models.IntegerChoices):
        """A webhook type."""

        DISCORD = 1, _("Discord Webhook")

    name = models.CharField(
        max_length=64, unique=True, help_text="short name to identify this webhook"
    )
    webhook_type = models.IntegerField(
        choices=WebhookType.choices,
        default=WebhookType.DISCORD,
        help_text="type of this webhook",
    )
    url = models.CharField(
        max_length=255,
        unique=True,
        help_text=(
            "URL of this webhook, e.g. "
            "https://discordapp.com/api/webhooks/123456/abcdef"
        ),
    )
    notes = models.TextField(
        blank=True,
        help_text="you can add notes about this webhook here if you want",
    )
    is_enabled = models.BooleanField(
        default=True,
        db_index=True,
        help_text="whether notifications are currently sent to this webhook",
    )
    objects = WebhookManager()

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.main_queue = self._create_queue("main")
        self.error_queue = self._create_queue("error")

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id={self.id}, name='{self.name}')"  # type: ignore

    def __getstate__(self):
        # Copy the object's state from self.__dict__ which contains
        # all our instance attributes. Always use the dict.copy()
        # method to avoid modifying the original state.
        state = self.__dict__.copy()
        # Remove the unpicklable entries.
        del state["main_queue"]
        del state["error_queue"]
        return state

    def __setstate__(self, state):
        # Restore instance attributes (i.e., filename and lineno).
        self.__dict__.update(state)
        # Restore the previously opened file's state. To do so, we need to
        # reopen it and read from it until the line count is restored.
        self.main_queue = self._create_queue("main")
        self.error_queue = self._create_queue("error")

    def save(self, *args, **kwargs):
        is_new = self.id is None  # type: ignore
        super().save(*args, **kwargs)
        if is_new:
            self.main_queue = self._create_queue("main")
            self.error_queue = self._create_queue("error")

    def _create_queue(self, suffix: str) -> Optional[SimpleMQ]:
        redis_client = get_redis_client()
        return (
            SimpleMQ(redis_client, f"{__title__}_webhook_{self.pk}_{suffix}")
            if self.pk
            else None
        )

    def reset_failed_messages(self) -> int:
        """moves all messages from error queue into main queue.
        returns number of moved messages.
        """
        counter = 0
        if self.error_queue and self.main_queue:
            while True:
                message = self.error_queue.dequeue()
                if message is None:
                    break

                self.main_queue.enqueue(message)
                counter += 1

        return counter

    def enqueue_message(
        self,
        content: Optional[str] = None,
        embeds: Optional[List[dhooks_lite.Embed]] = None,
        tts: Optional[bool] = None,
        username: Optional[str] = None,
        avatar_url: Optional[str] = None,
    ) -> int:
        """Enqueues a message to be send with this webhook"""
        if not self.main_queue:
            return 0

        username = __title__ if KILLTRACKER_WEBHOOK_SET_AVATAR else username
        brand_url = static_file_absolute_url("killtracker/killtracker_logo.png")
        avatar_url = brand_url if KILLTRACKER_WEBHOOK_SET_AVATAR else avatar_url
        return self.main_queue.enqueue(
            self._discord_message_asjson(
                content=content,
                embeds=embeds,
                tts=tts,
                username=username,
                avatar_url=avatar_url,
            )
        )

    @staticmethod
    def _discord_message_asjson(
        content: Optional[str] = None,
        embeds: Optional[List[dhooks_lite.Embed]] = None,
        tts: Optional[bool] = None,
        username: Optional[str] = None,
        avatar_url: Optional[str] = None,
    ) -> str:
        """Converts a Discord message to JSON and returns it

        Raises ValueError if message is incomplete
        """
        if not content and not embeds:
            raise ValueError("Message must have content or embeds to be valid")

        if embeds:
            embeds_list = [obj.asdict() for obj in embeds]
        else:
            embeds_list = None

        message = {}
        if content:
            message["content"] = content
        if embeds_list:
            message["embeds"] = embeds_list
        if tts:
            message["tts"] = tts
        if username:
            message["username"] = username
        if avatar_url:
            message["avatar_url"] = avatar_url

        return json.dumps(message, cls=JSONDateTimeEncoder)

    def send_message_to_webhook(self, message_json: str) -> dhooks_lite.WebhookResponse:
        """Send given message to webhook

        Params
            message_json: Discord message encoded in JSON
        """
        timeout = cache.ttl(self._blocked_cache_key())  # type: ignore
        if timeout:
            raise WebhookTooManyRequests(timeout)

        message = json.loads(message_json, cls=JSONDateTimeDecoder)
        if message.get("embeds"):
            embeds = [
                dhooks_lite.Embed.from_dict(embed_dict)
                for embed_dict in message.get("embeds")
            ]
        else:
            embeds = None
        hook = dhooks_lite.Webhook(
            url=self.url,
            user_agent=dhooks_lite.UserAgent(
                name=APP_NAME, url=HOMEPAGE_URL, version=__version__
            ),
        )
        response = hook.execute(
            content=message.get("content"),
            embeds=embeds,
            username=message.get("username"),
            avatar_url=message.get("avatar_url"),
            wait_for_response=True,
            max_retries=0,  # we will handle retries ourselves
        )
        logger.debug("headers: %s", response.headers)
        logger.debug("status_code: %s", response.status_code)
        logger.debug("content: %s", response.content)
        if response.status_code == self.HTTP_TOO_MANY_REQUESTS:
            logger.error(
                "%s: Received too many requests error from API: %s",
                self,
                response.content,
            )
            try:
                retry_after = int(response.headers["Retry-After"]) + 2
            except (ValueError, KeyError):
                retry_after = WebhookTooManyRequests.DEFAULT_RESET_AFTER
            cache.set(
                key=self._blocked_cache_key(), value="BLOCKED", timeout=retry_after
            )
            raise WebhookTooManyRequests(retry_after)
        return response

    def _blocked_cache_key(self) -> str:
        return f"{__title__}_webhook_{self.pk}_blocked"

    @staticmethod
    def create_message_link(name: str, url: str) -> str:
        """Create link for a Discord message"""
        if name and url:
            return f"[{str(name)}]({str(url)})"
        return str(name)


class Tracker(models.Model):
    """A tracker for killmails."""

    class ChannelPingType(models.TextChoices):
        """A channel ping type."""

        NONE = "PN", "(none)"
        HERE = "PH", "@here"
        EVERYBODY = "PE", "@everybody"

    name = models.CharField(
        max_length=100,
        help_text="Name to identify tracker. Will be shown on alerts posts.",
        unique=True,
    )
    description = models.TextField(
        blank=True,
        help_text=(
            "Brief description what this tracker is for. Will not be shown on alerts."
        ),
    )
    color = models.CharField(
        max_length=7,
        default="",
        blank=True,
        help_text=(
            "Optional color for embed on Discord - #000000 / "
            "black means no color selected."
        ),
    )
    origin_solar_system = models.ForeignKey(
        EveSolarSystem,
        on_delete=models.SET_DEFAULT,
        default=None,
        null=True,
        blank=True,
        related_name="+",
        help_text=(
            "Solar system to calculate distance and jumps from. "
            "When provided distance and jumps will be shown on killmail messages."
        ),
    )
    require_max_jumps = models.PositiveIntegerField(
        default=None,
        null=True,
        blank=True,
        help_text=(
            "Require all killmails to be max x jumps away from origin solar system."
        ),
    )
    require_max_distance = models.FloatField(
        default=None,
        null=True,
        blank=True,
        help_text=(
            "Require all killmails to be max x LY away from origin solar system."
        ),
    )
    exclude_attacker_alliances = models.ManyToManyField(
        EveAllianceInfo,
        related_name="+",
        default=None,
        blank=True,
        help_text="Exclude killmails with attackers from one of these alliances. ",
    )
    require_attacker_alliances = models.ManyToManyField(
        EveAllianceInfo,
        related_name="+",
        default=None,
        blank=True,
        help_text="Only include killmails with attackers from one of these alliances. ",
    )
    exclude_attacker_corporations = models.ManyToManyField(
        EveCorporationInfo,
        related_name="+",
        default=None,
        blank=True,
        help_text="Exclude killmails with attackers from one of these corporations. ",
    )
    require_attacker_corporations = models.ManyToManyField(
        EveCorporationInfo,
        related_name="+",
        default=None,
        blank=True,
        help_text=(
            "Only include killmails with attackers from one of these corporations. "
        ),
    )
    require_attacker_organizations_final_blow = models.BooleanField(
        default=False,
        blank=True,
        help_text=(
            "Only include killmails where at least one of the specified "
            "<b>required attacker corporations</b> or "
            "<b>required attacker alliances</b> "
            "has the final blow."
        ),
    )
    exclude_attacker_states = models.ManyToManyField(
        State,
        related_name="+",
        default=None,
        blank=True,
        help_text=(
            "Exclude killmails with characters belonging "
            "to users with these Auth states. "
        ),
    )
    require_attacker_states = models.ManyToManyField(
        State,
        related_name="+",
        default=None,
        blank=True,
        help_text=(
            "Only include killmails with characters belonging "
            "to users with these Auth states. "
        ),
    )
    require_victim_alliances = models.ManyToManyField(
        EveAllianceInfo,
        related_name="+",
        default=None,
        blank=True,
        help_text=(
            "Only include killmails where the victim belongs "
            "to one of these alliances. "
        ),
    )
    exclude_victim_alliances = models.ManyToManyField(
        EveAllianceInfo,
        related_name="+",
        default=None,
        blank=True,
        help_text=(
            "Exclude killmails where the victim belongs to one of these alliances. "
        ),
    )
    require_victim_corporations = models.ManyToManyField(
        EveCorporationInfo,
        related_name="+",
        default=None,
        blank=True,
        help_text=(
            "Only include killmails where the victim belongs "
            "to one of these corporations. "
        ),
    )
    exclude_victim_corporations = models.ManyToManyField(
        EveCorporationInfo,
        related_name="+",
        default=None,
        blank=True,
        help_text=(
            "Exclude killmails where the victim belongs to one of these corporations. "
        ),
    )
    require_victim_states = models.ManyToManyField(
        State,
        related_name="+",
        default=None,
        blank=True,
        help_text=(
            "Only include killmails where the victim characters belong "
            "to users with these Auth states. "
        ),
    )
    identify_fleets = models.BooleanField(
        default=False,
        help_text="When true: kills are interpreted and shown as fleet kills.",
    )
    exclude_blue_attackers = models.BooleanField(
        default=False,
        help_text="Exclude killmails with blue attackers.",
    )
    require_blue_victim = models.BooleanField(
        default=False,
        help_text=(
            "Only include killmails where the victim has standing with our group."
        ),
    )
    require_min_attackers = models.PositiveIntegerField(
        default=None,
        null=True,
        blank=True,
        help_text="Require killmails to have at least given number of attackers.",
    )
    require_max_attackers = models.PositiveIntegerField(
        default=None,
        null=True,
        blank=True,
        help_text="Require killmails to have no more than max number of attackers.",
    )
    exclude_high_sec = models.BooleanField(
        default=False,
        help_text=(
            "Exclude killmails from high sec. "
            "Also exclude high sec systems in route finder for jumps from origin."
        ),
    )
    exclude_low_sec = models.BooleanField(
        default=False, help_text="Exclude killmails from low sec."
    )
    exclude_null_sec = models.BooleanField(
        default=False, help_text="Exclude killmails from null sec."
    )
    exclude_w_space = models.BooleanField(
        default=False, help_text="Exclude killmails from WH space."
    )
    require_regions = models.ManyToManyField(
        EveRegion,
        default=None,
        blank=True,
        related_name="+",
        help_text="Only include killmails that occurred in one of these regions. ",
    )
    require_constellations = models.ManyToManyField(
        EveConstellation,
        default=None,
        blank=True,
        related_name="+",
        help_text="Only include killmails that occurred in one of these regions. ",
    )
    require_solar_systems = models.ManyToManyField(
        EveSolarSystem,
        default=None,
        blank=True,
        related_name="+",
        help_text="Only include killmails that occurred in one of these regions. ",
    )
    require_min_value = models.PositiveIntegerField(
        default=None,
        null=True,
        blank=True,
        help_text=(
            "Require killmail's value to be greater "
            "or equal to the given value in M ISK."
        ),
    )
    require_attackers_ship_groups = models.ManyToManyField(
        EveGroup,
        related_name="+",
        default=None,
        blank=True,
        help_text=(
            "Only include killmails where at least one attacker "
            "is flying one of these ship groups. "
        ),
    )
    require_attackers_ship_types = models.ManyToManyField(
        EveType,
        related_name="+",
        default=None,
        blank=True,
        help_text=(
            "Only include killmails where at least one attacker "
            "is flying one of these ship types. "
        ),
    )
    require_attackers_weapon_groups = models.ManyToManyField(
        EveGroup,
        related_name="+",
        default=None,
        blank=True,
        help_text=(
            "Only include killmails where at least one attacker "
            "is using one of these weapon groups. "
        ),
    )
    require_attackers_weapon_types = models.ManyToManyField(
        EveType,
        related_name="+",
        default=None,
        blank=True,
        help_text=(
            "Only include killmails where at least one attacker "
            "is using one of these weapon types. "
        ),
    )
    require_victim_ship_groups = models.ManyToManyField(
        EveGroup,
        related_name="+",
        default=None,
        blank=True,
        help_text=(
            "Only include killmails where victim is flying one of these ship groups. "
        ),
    )
    require_victim_ship_types = models.ManyToManyField(
        EveType,
        related_name="+",
        default=None,
        blank=True,
        help_text=(
            "Only include killmails where victim is flying one of these ship types. "
        ),
    )
    exclude_npc_kills = models.BooleanField(
        default=False, help_text="Exclude npc kills."
    )
    require_npc_kills = models.BooleanField(
        default=False, help_text="Only include killmails that are npc kills."
    )
    webhook = models.ForeignKey(
        Webhook,
        on_delete=models.CASCADE,
        help_text="Webhook URL for a channel on Discord to sent all alerts to.",
    )
    ping_type = models.CharField(
        max_length=2,
        choices=ChannelPingType.choices,
        default=ChannelPingType.NONE,
        verbose_name="channel pings",
        help_text="Option to ping every member of the channel.",
    )
    ping_groups = models.ManyToManyField(
        Group,
        default=None,
        blank=True,
        verbose_name="group pings",
        related_name="+",
        help_text="Option to ping specific group members. ",
    )
    is_posting_name = models.BooleanField(
        default=True, help_text="Whether posted messages include the tracker's name."
    )
    is_enabled = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Toogle for activating or deactivating a tracker.",
    )

    objects = TrackerManager()

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if self.color == "#000000":
            self.color = ""
        super().save(*args, **kwargs)

    @property
    def has_localization_clause(self) -> bool:
        """returns True if tracker has a clause that needs the killmails's solar system"""
        return (
            self.exclude_high_sec
            or self.exclude_low_sec
            or self.exclude_null_sec
            or self.exclude_w_space
            or self.require_max_distance is not None
            or self.require_max_jumps is not None
            or self.require_regions.exists()
            or self.require_constellations.exists()
            or self.require_solar_systems.exists()
        )

    @property
    def has_type_clause(self) -> bool:
        """returns True if tracker has a clause that needs a type from the killmail,
        e.g. the ship type of the victim
        """
        return (
            self.require_attackers_ship_groups.exists()
            or self.require_attackers_ship_types.exists()
            or self.require_victim_ship_groups.exists()
            or self.require_victim_ship_types.exists()
        )

    def process_killmail(
        self, killmail: Killmail, ignore_max_age: bool = False
    ) -> Optional[Killmail]:
        """Run tracker on a killmail and see if it matches

        Args:
        - killmail: Killmail to process
        - ignore_max_age: Whether to discord killmails that are older then the defined threshold

        Returns:
        - Copy of killmail with added tracker info if it matches or None if there is no match
        """
        threshold_date = now() - timedelta(
            minutes=KILLTRACKER_KILLMAIL_MAX_AGE_FOR_TRACKER
        )
        if not ignore_max_age and killmail.time < threshold_date:
            return None

        # Make sure all ship types are in the local database
        if self.has_type_clause:
            EveType.objects.bulk_get_or_create_esi(  # type: ignore
                ids=killmail.ship_type_distinct_ids()
            )

        # match against clauses
        is_matching = True
        distance = None
        jumps = None
        matching_ship_type_ids = []
        try:
            is_matching = self._match_npc(killmail, is_matching)
            is_matching = self._match_value(killmail, is_matching)
            is_matching, jumps, distance = self._match_geography(killmail, is_matching)
            is_matching = self._match_attackers(killmail, is_matching)
            is_matching, matching_ship_type_ids = self._match_attacker_ships(
                killmail, is_matching, matching_ship_type_ids
            )
            is_matching = self._match_attacker_weapons(killmail, is_matching)
            is_matching = self._match_victims(killmail, is_matching)
            is_matching, matching_ship_type_ids = self._match_victim_ship(
                killmail, is_matching, matching_ship_type_ids
            )

        except AttributeError:
            is_matching = False

        if not is_matching:
            return None

        killmail_new = killmail.clone_with_tracker_info(
            tracker_pk=self.pk,
            jumps=jumps,
            distance=distance,
            matching_ship_type_ids=matching_ship_type_ids,
        )
        return killmail_new

    def _match_npc(self, killmail: Killmail, is_matching: bool) -> bool:
        if is_matching and self.exclude_npc_kills:
            is_matching = not bool(killmail.zkb.is_npc)

        if is_matching and self.require_npc_kills:
            is_matching = bool(killmail.zkb.is_npc)
        return is_matching

    def _match_value(self, killmail: Killmail, is_matching: bool) -> bool:
        if is_matching and self.require_min_value:
            is_matching = (
                killmail.zkb.total_value is not None
                and killmail.zkb.total_value >= self.require_min_value * 1_000_000
            )

        return is_matching

    def _match_geography(
        self, killmail: Killmail, is_matching: bool
    ) -> Tuple[bool, Optional[int], Optional[float]]:
        if (
            not killmail.solar_system_id
            or not self.origin_solar_system
            and not self.has_localization_clause
        ):
            return is_matching, None, None

        solar_system: EveSolarSystem = EveSolarSystem.objects.get_or_create_esi(  # type: ignore
            id=killmail.solar_system_id
        )[
            0
        ]

        jumps, distance = self._calc_distances(solar_system)

        if is_matching and self.exclude_high_sec:
            is_matching = not solar_system.is_high_sec

        if is_matching and self.exclude_low_sec:
            is_matching = not solar_system.is_low_sec

        if is_matching and self.exclude_null_sec:
            is_matching = not solar_system.is_null_sec

        if is_matching and self.exclude_w_space:
            is_matching = not solar_system.is_w_space

        if is_matching and self.require_max_distance:
            is_matching = distance is not None and (
                distance <= self.require_max_distance
            )

        if is_matching and self.require_max_jumps:
            is_matching = jumps is not None and (jumps <= self.require_max_jumps)

        if is_matching and self.require_regions.exists():
            is_matching = (
                solar_system
                and self.require_regions.filter(
                    id=solar_system.eve_constellation.eve_region_id
                ).exists()
            )

        if is_matching and self.require_constellations.exists():
            is_matching = (
                solar_system
                and self.require_constellations.filter(
                    id=solar_system.eve_constellation_id  # type: ignore
                ).exists()
            )

        if is_matching and self.require_solar_systems.exists():
            is_matching = (
                solar_system
                and self.require_solar_systems.filter(id=solar_system.id).exists()
            )

        return is_matching, jumps, distance

    def _calc_distances(
        self, solar_system: EveSolarSystem
    ) -> Tuple[Optional[int], Optional[float]]:
        if not self.origin_solar_system:
            return None, None

        distance_raw = self.origin_solar_system.distance_to(solar_system)
        distance = meters_to_ly(distance_raw) if distance_raw is not None else None
        try:
            jumps = self.origin_solar_system.jumps_to(solar_system)
        except OSError:
            # Currently all those exceptions are already captures in eveuniverse,
            # but this shall remain for when the workaround is fixed
            jumps = None
        return (jumps, distance)

    def _match_attackers(self, killmail: Killmail, is_matching: bool) -> bool:
        if is_matching and self.require_min_attackers:
            is_matching = len(killmail.attackers) >= self.require_min_attackers

        if is_matching and self.require_max_attackers:
            is_matching = len(killmail.attackers) <= self.require_max_attackers

        if is_matching and self.exclude_attacker_alliances.exists():
            is_matching = self.exclude_attacker_alliances.exclude(
                alliance_id__in=killmail.attackers_distinct_alliance_ids()
            ).exists()

        if is_matching and self.exclude_attacker_corporations.exists():
            is_matching = self.exclude_attacker_corporations.exclude(
                corporation_id__in=killmail.attackers_distinct_corporation_ids()
            ).exists()

        if is_matching:
            if self.require_attacker_organizations_final_blow:
                attacker_final_blow = killmail.attacker_final_blow()
                is_matching = bool(attacker_final_blow) and (
                    (
                        bool(attacker_final_blow.alliance_id)
                        and self.require_attacker_alliances.filter(
                            alliance_id=attacker_final_blow.alliance_id
                        ).exists()
                    )
                    | (
                        bool(attacker_final_blow.corporation_id)
                        and self.require_attacker_corporations.filter(
                            corporation_id=attacker_final_blow.corporation_id
                        ).exists()
                    )
                )
            else:
                if is_matching and self.require_attacker_alliances.exists():
                    is_matching = self.require_attacker_alliances.filter(
                        alliance_id__in=killmail.attackers_distinct_alliance_ids()
                    ).exists()
                if is_matching and self.require_attacker_corporations.exists():
                    is_matching = self.require_attacker_corporations.filter(
                        corporation_id__in=killmail.attackers_distinct_corporation_ids()
                    ).exists()

        if is_matching and self.require_attacker_states.exists():
            is_matching = User.objects.filter(
                profile__state__in=list(self.require_attacker_states.all()),
                character_ownerships__character__character_id__in=(
                    killmail.attackers_distinct_character_ids()
                ),
            ).exists()

        if is_matching and self.exclude_attacker_states.exists():
            is_matching = not User.objects.filter(
                profile__state__in=list(self.exclude_attacker_states.all()),
                character_ownerships__character__character_id__in=(
                    killmail.attackers_distinct_character_ids()
                ),
            ).exists()

        return is_matching

    def _match_attacker_ships(
        self, killmail: Killmail, is_matching: bool, matching_ship_type_ids: List[int]
    ) -> Tuple[bool, List[int]]:
        if is_matching and self.require_attackers_ship_groups.exists():
            ship_types_matching_qs = EveType.objects.filter(
                id__in=set(killmail.attackers_ship_type_ids())
            ).filter(
                eve_group_id__in=list(
                    self.require_attackers_ship_groups.values_list("id", flat=True)
                )
            )
            is_matching = ship_types_matching_qs.exists()
            if is_matching:
                matching_ship_type_ids = list(
                    ship_types_matching_qs.values_list("id", flat=True)
                )

        if is_matching and self.require_attackers_ship_types.exists():
            ship_types_matching_qs = EveType.objects.filter(
                id__in=set(killmail.attackers_ship_type_ids())
            ).filter(
                id__in=list(
                    self.require_attackers_ship_types.values_list("id", flat=True)
                )
            )
            is_matching = ship_types_matching_qs.exists()
            if is_matching:
                matching_ship_type_ids = list(
                    ship_types_matching_qs.values_list("id", flat=True)
                )

        return is_matching, matching_ship_type_ids

    def _match_attacker_weapons(
        self, killmail: Killmail, is_matching: bool
    ) -> Tuple[bool, List[int]]:
        if is_matching and self.require_attackers_weapon_groups.exists():
            weapon_types_matching_qs = EveType.objects.filter(
                id__in=set(killmail.attackers_weapon_type_ids())
            ).filter(
                eve_group_id__in=list(
                    self.require_attackers_weapon_groups.values_list("id", flat=True)
                )
            )
            is_matching = weapon_types_matching_qs.exists()

        if is_matching and self.require_attackers_weapon_types.exists():
            weapon_types_matching_qs = EveType.objects.filter(
                id__in=set(killmail.attackers_weapon_type_ids())
            ).filter(
                id__in=list(
                    self.require_attackers_weapon_types.values_list("id", flat=True)
                )
            )
            is_matching = weapon_types_matching_qs.exists()

        return is_matching

    def _match_victims(self, killmail: Killmail, is_matching: bool) -> bool:
        if is_matching and self.require_victim_alliances.exists():
            is_matching = self.require_victim_alliances.filter(
                alliance_id=killmail.victim.alliance_id
            ).exists()

        if is_matching and self.exclude_victim_alliances.exists():
            is_matching = self.exclude_victim_alliances.exclude(
                alliance_id=killmail.victim.alliance_id
            ).exists()

        if is_matching and self.require_victim_corporations.exists():
            is_matching = self.require_victim_corporations.filter(
                corporation_id=killmail.victim.corporation_id
            ).exists()

        if is_matching and self.exclude_victim_corporations.exists():
            is_matching = self.exclude_victim_corporations.exclude(
                corporation_id=killmail.victim.corporation_id
            ).exists()

        if is_matching and self.require_victim_states.exists():
            is_matching = User.objects.filter(
                profile__state__in=list(self.require_victim_states.all()),
                character_ownerships__character__character_id=(
                    killmail.victim.character_id
                ),
            ).exists()

        return is_matching

    def _match_victim_ship(
        self, killmail: Killmail, is_matching: bool, matching_ship_type_ids: List[int]
    ) -> Tuple[bool, List[int]]:
        if is_matching and self.require_victim_ship_groups.exists():
            ship_types_matching_qs = EveType.objects.filter(
                eve_group_id__in=list(
                    self.require_victim_ship_groups.values_list("id", flat=True)
                ),
                id=killmail.victim.ship_type_id,
            )
            is_matching = ship_types_matching_qs.exists()
            if is_matching:
                matching_ship_type_ids = list(
                    ship_types_matching_qs.values_list("id", flat=True)
                )

        if is_matching and self.require_victim_ship_types.exists():
            ship_types_matching_qs = EveType.objects.filter(
                id__in=list(
                    self.require_victim_ship_types.values_list("id", flat=True)
                ),
                id=killmail.victim.ship_type_id,
            )
            is_matching = ship_types_matching_qs.exists()
            if is_matching:
                matching_ship_type_ids = list(
                    ship_types_matching_qs.values_list("id", flat=True)
                )

        return is_matching, matching_ship_type_ids

    def generate_killmail_message(
        self, killmail: Killmail, intro_text: Optional[str] = None
    ) -> int:
        """generate a message from given killmail and enqueue for later sending

        returns new queue size
        """
        from killtracker.core import discord_messages

        content = discord_messages.create_content(self, intro_text)
        embed = discord_messages.create_embed(self, killmail)
        return self.webhook.enqueue_message(content=content, embeds=[embed])
