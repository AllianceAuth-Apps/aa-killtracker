"""Create discord messages from killmails."""

from typing import NamedTuple, Optional

import dhooks_lite
from requests.exceptions import HTTPError

from eveuniverse.helpers import EveEntityNameResolver
from eveuniverse.models import EveEntity, EveSolarSystem

from allianceauth.eveonline.evelinks import dotlan, eveimageserver, zkillboard
from allianceauth.services.hooks import get_extension_logger
from app_utils.django import app_labels
from app_utils.logging import LoggerAddTag
from app_utils.urls import static_file_absolute_url
from app_utils.views import humanize_value

from killtracker import __title__
from killtracker.models import Tracker

from .killmails import ZKB_KILLMAIL_BASEURL, Killmail, TrackerInfo

ICON_SIZE = 128


logger = LoggerAddTag(get_extension_logger(__name__), __title__)


class MainOrgInfo(NamedTuple):
    """Infos about a main organization."""

    text: str = ""
    name: str = ""
    icon_url: str = eveimageserver.alliance_logo_url(1, size=ICON_SIZE)
    show_as_fleet_kill: bool = False


class FinalAttackerInfo(NamedTuple):
    """Infos about the final attacker on a killmail."""

    name: str = ""
    ship_type: str = ""


class VictimInfo(NamedTuple):
    """Infos about the victim of a killmail."""

    name: str
    organization: str
    org_url: str
    org_icon_url: str
    ship_type: str
    ship_type_icon_url: str


def create_content(tracker: Tracker, intro_text: Optional[str] = None) -> str:
    """Create content for Discord message for a killmail."""

    intro_parts = []

    if tracker.ping_type == Tracker.ChannelPingType.EVERYBODY:
        intro_parts.append("@everybody")
    elif tracker.ping_type == Tracker.ChannelPingType.HERE:
        intro_parts.append("@here")

    if tracker.ping_groups.exists():
        if "discord" in app_labels():
            DiscordUser = _import_discord_user()
            for group in tracker.ping_groups.all():
                try:
                    role = DiscordUser.objects.group_to_role(group)  # type: ignore
                except HTTPError:
                    logger.warning(
                        "Failed to get Discord roles. Can not ping groups.",
                        exc_info=True,
                    )
                else:
                    if role:
                        intro_parts.append(f"<@&{role['id']}>")

        else:
            logger.warning(
                "Discord service needs to be installed in order "
                "to use groups ping features."
            )

    if tracker.is_posting_name:
        intro_parts.append(f"Tracker **{tracker.name}**:")

    intro_parts_2 = []
    if intro_text:
        intro_parts_2.append(intro_text)
    if intro_parts:
        intro_parts_2.append(" ".join(intro_parts))

    return "\n".join(intro_parts_2)


def _import_discord_user():
    from allianceauth.services.modules.discord.models import DiscordUser

    return DiscordUser


def create_embed(tracker: Tracker, killmail: Killmail) -> dhooks_lite.Embed:
    """Create Discord embed for a killmail."""

    resolver: EveEntityNameResolver = EveEntity.objects.bulk_resolve_names(  # type: ignore
        ids=killmail.entity_ids()
    )

    # self info
    distance_text = ""
    main_org = MainOrgInfo()
    main_ship_group_text = ""
    tracked_ship_types_text = ""

    if killmail.tracker_info:
        distance_text = _calc_distance(tracker, killmail.tracker_info)
        main_org = _calc_main_group(tracker, killmail.tracker_info, resolver)
        main_ship_group_text = _calc_main_ship_group(killmail.tracker_info)
        tracked_ship_types_text = _calc_tracked_ship_types(
            killmail.tracker_info, resolver
        )

    victim = _calc_victim(tracker, killmail, resolver)
    description = _calc_description(
        tracker,
        killmail,
        resolver,
        distance_text,
        main_org,
        main_ship_group_text,
        tracked_ship_types_text,
        victim,
    )
    title = _calc_title(killmail, resolver, main_org, victim)
    thumbnail_url = _calc_thumbnail_url(victim, main_org)

    return _create_embed(killmail, tracker, victim, description, title, thumbnail_url)


def _calc_author(victim: VictimInfo):
    # TODO This is a workaround for Embed.Author.name. Address in dhooks_lite
    return (
        dhooks_lite.Author(
            name=victim.organization if victim.organization else "?",
            url=victim.org_url,
            icon_url=victim.org_icon_url,
        )
        if victim.organization and victim.org_url and victim.org_icon_url
        else None
    )


def _calc_description(
    tracker: Tracker,
    killmail: Killmail,
    resolver: EveEntityNameResolver,
    distance_text: str,
    main_org: MainOrgInfo,
    main_ship_group_text: str,
    tracked_ship_types_text: str,
    victim: VictimInfo,
):
    solar_system_text = _calc_solar_system(tracker, killmail)
    total_value = (
        humanize_value(killmail.zkb.total_value) if killmail.zkb.total_value else "?"
    )
    final_attacker = _calc_final_attacker(tracker, killmail, resolver)

    description = (
        f"{victim.name} lost their **{victim.ship_type}** "
        f"in {solar_system_text} "
        f"worth **{total_value}** ISK.\n"
        f"Final blow by {final_attacker.name} "
        f"in a **{final_attacker.ship_type}**.\n"
        f"Attackers: **{len(killmail.attackers):,}**{main_org.text}"
        f"{main_ship_group_text}"
        f"{tracked_ship_types_text}"
        f"{distance_text}"
    )

    return description


def _calc_victim(
    tracker: Tracker, killmail: Killmail, resolver: EveEntityNameResolver
) -> VictimInfo:
    if killmail.victim.alliance_id:
        victim_organization = resolver.to_name(killmail.victim.alliance_id)
        victim_org_url = zkillboard.alliance_url(killmail.victim.alliance_id)
        victim_org_icon_url = eveimageserver.alliance_logo_url(
            killmail.victim.alliance_id, size=ICON_SIZE
        )
    elif killmail.victim.corporation_id:
        victim_organization = resolver.to_name(killmail.victim.corporation_id)
        victim_org_url = zkillboard.corporation_url(killmail.victim.corporation_id)
        victim_org_icon_url = eveimageserver.corporation_logo_url(
            killmail.victim.corporation_id, size=ICON_SIZE
        )
    else:
        victim_organization = ""
        victim_org_url = ""
        victim_org_icon_url = ""

    if killmail.victim.corporation_id:
        victim_corporation_zkb_link = _corporation_zkb_link(
            tracker, killmail.victim.corporation_id, resolver
        )
    else:
        victim_corporation_zkb_link = ""

    if killmail.victim.character_id:
        victim_character_zkb_link = _character_zkb_link(
            tracker, killmail.victim.character_id, resolver
        )
        victim_str = f"{victim_character_zkb_link} ({victim_corporation_zkb_link})"
    elif killmail.victim.corporation_id:
        victim_str = victim_corporation_zkb_link
    else:
        victim_str = ""

    try:
        ship_type_id = killmail.victim.ship_type_id
    except AttributeError:
        ship_type_id = None

    ship_type = resolver.to_name(ship_type_id) if ship_type_id else ""

    ship_type_icon_url = (
        eveimageserver.type_icon_url(ship_type_id, size=ICON_SIZE)
        if ship_type_id
        else ""
    )

    return VictimInfo(
        organization=victim_organization,
        org_url=victim_org_url,
        org_icon_url=victim_org_icon_url,
        name=victim_str,
        ship_type=ship_type,
        ship_type_icon_url=ship_type_icon_url,
    )


def _calc_final_attacker(
    tracker: Tracker, killmail: Killmail, resolver: EveEntityNameResolver
) -> FinalAttackerInfo:
    for attacker in killmail.attackers:
        if attacker.is_final_blow:
            final_attacker = attacker
            break
    else:
        final_attacker = None

    if not final_attacker:
        return FinalAttackerInfo()

    if final_attacker.corporation_id:
        final_attacker_corporation_zkb_link = _corporation_zkb_link(
            tracker, final_attacker.corporation_id, resolver
        )
    else:
        final_attacker_corporation_zkb_link = ""

    if final_attacker.character_id and final_attacker.corporation_id:
        final_attacker_character_zkb_link = _character_zkb_link(
            tracker, final_attacker.character_id, resolver
        )
        final_attacker_str = (
            f"{final_attacker_character_zkb_link} "
            f"({final_attacker_corporation_zkb_link})"
        )
    elif final_attacker.corporation_id:
        final_attacker_str = f"{final_attacker_corporation_zkb_link}"
    elif final_attacker.faction_id:
        final_attacker_str = f"**{resolver.to_name(final_attacker.faction_id)}**"
    else:
        final_attacker_str = "(Unknown final_attacker)"

    try:
        ship_type_id = final_attacker.ship_type_id
    except AttributeError:
        ship_type_id = None

    ship_type = resolver.to_name(ship_type_id) if ship_type_id else ""

    return FinalAttackerInfo(name=final_attacker_str, ship_type=ship_type)


def _calc_solar_system(tracker: Tracker, killmail: Killmail):
    if not killmail.solar_system_id:
        return ""

    solar_system, _ = EveSolarSystem.objects.get_or_create_esi(  # type: ignore
        id=killmail.solar_system_id
    )
    solar_system_link = tracker.webhook.create_message_link(
        name=solar_system.name, url=dotlan.solar_system_url(solar_system.name)
    )
    region_name = solar_system.eve_constellation.eve_region.name
    return f"{solar_system_link} ({region_name})"


def _calc_distance(tracker: Tracker, tracker_info: TrackerInfo):
    if not tracker.origin_solar_system:
        return ""

    origin_solar_system_link = tracker.webhook.create_message_link(
        name=tracker.origin_solar_system.name,
        url=dotlan.solar_system_url(tracker.origin_solar_system.name),
    )
    if tracker_info.distance is not None:
        distance_str = f"{tracker_info.distance:,.1f}"
    else:
        distance_str = "?"

    if tracker_info.jumps is not None:
        jumps_str = tracker_info.jumps
    else:
        jumps_str = "?"

    return (
        f"\nDistance from {origin_solar_system_link}: "
        f"{distance_str} LY | {jumps_str} jumps"
    )


def _calc_main_group(
    tracker: Tracker,
    tracker_info: TrackerInfo,
    resolver: EveEntityNameResolver,
):
    main_org_entity = tracker_info.main_org
    if main_org_entity:
        main_org_name = resolver.to_name(main_org_entity.id)
        if main_org_entity.is_corporation:
            main_org_link = _corporation_zkb_link(tracker, main_org_entity.id, resolver)
            main_org_icon_url = eveimageserver.corporation_logo_url(
                main_org_entity.id, size=ICON_SIZE
            )
        else:
            main_org_link = _alliance_zkb_link(tracker, main_org_entity.id, resolver)
            main_org_icon_url = eveimageserver.alliance_logo_url(
                main_org_entity.id, size=ICON_SIZE
            )
        main_org_text = f" | Main group: {main_org_link} ({main_org_entity.count})"
        show_as_fleet_kill = tracker.identify_fleets
    else:
        show_as_fleet_kill = False
        main_org_text = main_org_name = main_org_icon_url = ""

    return MainOrgInfo(
        text=main_org_text,
        name=main_org_name,
        icon_url=main_org_icon_url,
        show_as_fleet_kill=show_as_fleet_kill,
    )


def _calc_main_ship_group(tracker_info: TrackerInfo) -> str:
    main_ship_group = tracker_info.main_ship_group
    if not main_ship_group:
        return ""

    return f"\nMain ship class: **{main_ship_group.name}**"


def _calc_tracked_ship_types(
    tracker_info: TrackerInfo, resolver: EveEntityNameResolver
) -> str:
    matching_ship_type_ids = tracker_info.matching_ship_type_ids
    if not matching_ship_type_ids:
        return ""

    ship_types_text = "**, **".join(
        sorted([resolver.to_name(type_id) for type_id in matching_ship_type_ids])
    )
    return f"\nTracked ship types involved: **{ship_types_text}**"


def _calc_thumbnail_url(victim: VictimInfo, main_org: MainOrgInfo):
    if main_org.show_as_fleet_kill:
        return main_org.icon_url

    return victim.ship_type_icon_url


def _calc_title(
    killmail: Killmail,
    resolver: EveEntityNameResolver,
    main_org: MainOrgInfo,
    victim: VictimInfo,
):
    solar_system_name = (
        resolver.to_name(killmail.solar_system_id) if killmail.solar_system_id else ""
    )

    if main_org.show_as_fleet_kill:
        return f"{solar_system_name} | {main_org.name} | Fleetkill"

    return f"{solar_system_name} | {victim.ship_type} | Killmail"


def _create_embed(
    killmail: Killmail,
    tracker: Tracker,
    victim: VictimInfo,
    description: str,
    title: str,
    thumbnail_url: str,
):
    author = _calc_author(victim)
    zkb_icon_url = static_file_absolute_url("killtracker/zkb_icon.png")
    embed_color = int(tracker.color[1:], 16) if tracker and tracker.color else None

    embed = dhooks_lite.Embed(
        author=author,
        description=description,
        title=title,
        url=f"{ZKB_KILLMAIL_BASEURL}{killmail.id}/",
        thumbnail=dhooks_lite.Thumbnail(url=thumbnail_url),
        footer=dhooks_lite.Footer(text="zKillboard", icon_url=zkb_icon_url),
        timestamp=killmail.time,
        color=embed_color,
    )
    return embed


def _character_zkb_link(
    tracker: Tracker, entity_id: int, resolver: EveEntityNameResolver
) -> str:
    return tracker.webhook.create_message_link(
        name=resolver.to_name(entity_id), url=zkillboard.character_url(entity_id)
    )


def _corporation_zkb_link(
    tracker: Tracker, entity_id: int, resolver: EveEntityNameResolver
) -> str:
    return tracker.webhook.create_message_link(
        name=resolver.to_name(entity_id), url=zkillboard.corporation_url(entity_id)
    )


def _alliance_zkb_link(
    tracker: Tracker, entity_id: int, resolver: EveEntityNameResolver
) -> str:
    return tracker.webhook.create_message_link(
        name=resolver.to_name(entity_id), url=zkillboard.alliance_url(entity_id)
    )
