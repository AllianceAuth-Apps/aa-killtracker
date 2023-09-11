"""Global constants for killtracker."""

from enum import IntEnum

SESSION_KEY_TOOGLE_NPC = "killtracker_toogle_npc"
SESSION_KEY_USES_NPC = "killtracker_uses_npc"


class EveDogmaEffectId(IntEnum):
    """An Eve dogma effect ID."""

    HI_POWER = 12


class EveCategoryId(IntEnum):
    """An Eve category ID."""

    DEPLOYABLE = 22
    ENTITY = 11
    FIGHTER = 87
    MODULE = 7
    SHIP = 6
    STRUCTURE = 65


class EveGroupId(IntEnum):
    """An Eve group ID."""

    FRIGATE = 25
    MINING_DRONE = 101
    ORBITAL_INFRASTRUCTURE = 1025
    PROJECTILE_WEAPON = 55
    TACTICAL_DESTROYER = 1305
