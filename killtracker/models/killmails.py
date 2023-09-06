"""Killmail models for killtracker."""

from typing import Set

from django.db import models
from eveuniverse.models import EveEntity

from allianceauth.services.hooks import get_extension_logger
from app_utils.logging import LoggerAddTag

from killtracker import __title__
from killtracker.managers import EveKillmailManager

logger = LoggerAddTag(get_extension_logger(__name__), __title__)


class _EveKillmailCharacter(models.Model):
    """A character in a killmail for Eve Online. Can be both vitim and attacker."""

    character = models.ForeignKey(
        EveEntity,
        on_delete=models.CASCADE,
        default=None,
        null=True,
        blank=True,
        related_name="+",
    )
    corporation = models.ForeignKey(
        EveEntity,
        on_delete=models.CASCADE,
        default=None,
        null=True,
        blank=True,
        related_name="+",
    )
    alliance = models.ForeignKey(
        EveEntity,
        on_delete=models.CASCADE,
        default=None,
        null=True,
        blank=True,
        related_name="+",
    )
    faction = models.ForeignKey(
        EveEntity,
        on_delete=models.CASCADE,
        default=None,
        null=True,
        blank=True,
        related_name="+",
    )
    ship_type = models.ForeignKey(
        EveEntity,
        on_delete=models.CASCADE,
        default=None,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        abstract = True

    def entity_ids(self) -> Set[int]:
        """IDs of all entity objects."""
        ids = {
            self.character_id,  # type: ignore
            self.corporation_id,  # type: ignore
            self.alliance_id,  # type: ignore
            self.faction_id,  # type: ignore
            self.ship_type_id,  # type: ignore
        }
        ids.discard(None)
        return ids


class EveKillmail(_EveKillmailCharacter):
    """A killmail in Eve Online."""

    id = models.BigIntegerField(primary_key=True)
    time = models.DateTimeField(default=None, null=True, blank=True, db_index=True)
    solar_system = models.ForeignKey(
        EveEntity, on_delete=models.CASCADE, default=None, null=True, blank=True
    )
    updated_at = models.DateTimeField(auto_now=True)
    damage_taken = models.BigIntegerField(default=None, null=True, blank=True)
    # position
    position_x = models.FloatField(default=None, null=True, blank=True)
    position_y = models.FloatField(default=None, null=True, blank=True)
    position_z = models.FloatField(default=None, null=True, blank=True)
    # zkb
    location_id = models.PositiveIntegerField(
        default=None, null=True, blank=True, db_index=True
    )
    hash = models.CharField(max_length=64, default="", blank=True)
    fitted_value = models.FloatField(default=None, null=True, blank=True)
    total_value = models.FloatField(default=None, null=True, blank=True, db_index=True)
    zkb_points = models.PositiveIntegerField(
        default=None, null=True, blank=True, db_index=True
    )
    is_npc = models.BooleanField(default=None, null=True, blank=True, db_index=True)
    is_solo = models.BooleanField(default=None, null=True, blank=True, db_index=True)
    is_awox = models.BooleanField(default=None, null=True, blank=True, db_index=True)

    objects = EveKillmailManager()

    def __str__(self):
        return f"ID:{self.id}"

    def __repr__(self):
        return f"{type(self).__name__}(id={self.id})"

    def load_entities(self):
        """loads unknown entities for this killmail"""
        qs = EveEntity.objects.filter(id__in=self.entity_ids(), name="")
        qs.update_from_esi()  # type: ignore

    def entity_ids(self) -> Set[int]:
        """IDs of all entity objects."""
        ids = super().entity_ids() | {self.solar_system_id}  # type: ignore
        for attacker in self.attackers.all():  # type: ignore
            ids |= attacker.entity_ids()
        ids.discard(None)
        return ids


class EveKillmailAttacker(_EveKillmailCharacter):
    """An attacker on a killmail in Eve Online."""

    killmail = models.ForeignKey(
        EveKillmail, on_delete=models.CASCADE, related_name="attackers"
    )
    damage_done = models.BigIntegerField(default=None, null=True, blank=True)
    is_final_blow = models.BooleanField(
        default=None, null=True, blank=True, db_index=True
    )
    security_status = models.FloatField(default=None, null=True, blank=True)
    weapon_type = models.ForeignKey(
        EveEntity,
        on_delete=models.CASCADE,
        default=None,
        null=True,
        blank=True,
        related_name="+",
    )

    def __str__(self) -> str:
        if self.character:
            return str(self.character)
        if self.corporation:
            return str(self.corporation)
        if self.alliance:
            return str(self.alliance)
        if self.faction:
            return str(self.faction)
        return f"PK:{self.pk}"

    def entity_ids(self) -> Set[int]:
        """IDs of all entity objects."""
        ids = super().entity_ids()
        if self.weapon_type:
            ids.add(self.weapon_type.id)
        ids.discard(None)  # type: ignore
        return ids
