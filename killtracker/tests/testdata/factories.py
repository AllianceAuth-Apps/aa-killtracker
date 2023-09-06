import datetime as dt
from typing import Generic, Set, TypeVar

import factory
import factory.fuzzy

from django.utils.timezone import now
from eveuniverse.models import EveEntity

from killtracker.app_settings import KILLTRACKER_KILLMAIL_MAX_AGE_FOR_TRACKER
from killtracker.constants import EveCategoryId
from killtracker.core.killmails import (
    Killmail,
    KillmailAttacker,
    KillmailPosition,
    KillmailVictim,
    KillmailZkb,
    _KillmailCharacter,
)
from killtracker.models import EveKillmail, EveKillmailAttacker, Tracker, Webhook

from .load_eveuniverse import eveuniverse_testdata

T = TypeVar("T")


def _extract_faction_ids() -> Set[int]:
    faction_ids = {obj["id"] for obj in eveuniverse_testdata["EveFaction"]}
    return faction_ids


def _extract_solar_system_ids() -> Set[int]:
    system_ids = {obj["id"] for obj in eveuniverse_testdata["EveSolarSystem"]}
    return system_ids


def _extract_ship_type_ids() -> Set[int]:
    group_ids = {
        obj["id"]
        for obj in eveuniverse_testdata["EveGroup"]
        if obj["eve_category_id"] == EveCategoryId.SHIP
    }
    type_ids = {
        obj["id"]
        for obj in eveuniverse_testdata["EveType"]
        if obj["eve_group_id"] in group_ids
    }
    return type_ids


def _extract_weapon_type_ids() -> Set[int]:
    group_ids = {
        obj["id"]
        for obj in eveuniverse_testdata["EveGroup"]
        if obj["eve_category_id"] == EveCategoryId.MODULE
    }
    type_ids = {
        obj["id"]
        for obj in eveuniverse_testdata["EveType"]
        if obj["eve_group_id"] in group_ids
    }
    return type_ids


_faction_ids = _extract_faction_ids()
_solar_system_ids = _extract_solar_system_ids()
_ship_type_ids = _extract_ship_type_ids()
_weapon_type_ids = _extract_weapon_type_ids()


def random_eve_entity_faction(dummy):
    faction_id = factory.fuzzy.FuzzyChoice(_faction_ids).fuzz()
    return EveEntity.objects.get(id=faction_id)


def random_eve_entity_solar_system(dummy):
    solar_system_id = factory.fuzzy.FuzzyChoice(_solar_system_ids).fuzz()
    return EveEntity.objects.get(id=solar_system_id)


def random_eve_entity_ship_type(dummy):
    type_id = factory.fuzzy.FuzzyChoice(_ship_type_ids).fuzz()
    return EveEntity.objects.get(id=type_id)


def random_eve_entity_weapon_type(dummy):
    type_id = factory.fuzzy.FuzzyChoice(_weapon_type_ids).fuzz()
    return EveEntity.objects.get(id=type_id)


class BaseMetaFactory(Generic[T], factory.base.FactoryMetaClass):
    def __call__(cls, *args, **kwargs) -> T:
        return super().__call__(*args, **kwargs)


class EveEntityCharacterFactory(
    factory.django.DjangoModelFactory, metaclass=BaseMetaFactory[EveEntity]
):
    class Meta:
        model = EveEntity
        django_get_or_create = ("id",)

    id = factory.Sequence(lambda n: 90_000_001 + n)
    name = factory.faker.Faker("name")
    category = EveEntity.CATEGORY_CHARACTER


class EveEntityCorporationFactory(
    factory.django.DjangoModelFactory, metaclass=BaseMetaFactory[EveEntity]
):
    class Meta:
        model = EveEntity
        django_get_or_create = ("id",)

    id = factory.Sequence(lambda n: 98_000_001 + n)
    name = factory.faker.Faker("company")
    category = EveEntity.CATEGORY_CORPORATION


class EveEntityAllianceFactory(
    factory.django.DjangoModelFactory, metaclass=BaseMetaFactory[EveEntity]
):
    class Meta:
        model = EveEntity
        django_get_or_create = ("id",)

    id = factory.Sequence(lambda n: 99_000_001 + n)
    name = factory.faker.Faker("company")
    category = EveEntity.CATEGORY_ALLIANCE


class KillmailCharacterFactory(
    factory.Factory, metaclass=BaseMetaFactory[_KillmailCharacter]
):
    class Meta:
        model = _KillmailCharacter

    character_id = factory.Sequence(lambda n: 90_000_001 + n)
    corporation_id = factory.Sequence(lambda n: 98_000_001 + n)
    alliance_id = factory.Sequence(lambda n: 99_000_001 + n)
    faction_id = factory.fuzzy.FuzzyChoice(_faction_ids)
    ship_type_id = factory.fuzzy.FuzzyChoice(_ship_type_ids)


class KillmailVictimFactory(
    KillmailCharacterFactory, metaclass=BaseMetaFactory[KillmailVictim]
):
    class Meta:
        model = KillmailVictim

    damage_taken = factory.fuzzy.FuzzyInteger(1_000_000)


class KillmailAttackerFactory(
    KillmailCharacterFactory, metaclass=BaseMetaFactory[KillmailAttacker]
):
    class Meta:
        model = KillmailAttacker

    damage_done = factory.fuzzy.FuzzyInteger(1_000_000)
    security_status = factory.fuzzy.FuzzyFloat(-10.0, 5)
    weapon_type_id = factory.fuzzy.FuzzyChoice(_weapon_type_ids)


class KillmailPositionFactory(
    factory.Factory, metaclass=BaseMetaFactory[KillmailPosition]
):
    class Meta:
        model = KillmailPosition

    x = factory.fuzzy.FuzzyFloat(-10_000, 10_000)
    y = factory.fuzzy.FuzzyFloat(-10_000, 10_000)
    z = factory.fuzzy.FuzzyFloat(-10_000, 10_000)


class KillmailZkbFactory(factory.Factory, metaclass=BaseMetaFactory[KillmailZkb]):
    class Meta:
        model = KillmailZkb

    location_id = factory.Sequence(lambda n: n + 60_000_000)
    hash = factory.fuzzy.FuzzyText()
    fitted_value = factory.fuzzy.FuzzyFloat(10_000, 100_000_000)
    total_value = factory.LazyAttribute(lambda o: o.fitted_value)
    points = factory.fuzzy.FuzzyInteger(1000)
    is_npc = False
    is_solo = False
    is_awox = False


class KillmailFactory(factory.Factory, metaclass=BaseMetaFactory[Killmail]):
    class Meta:
        model = Killmail

    class Params:
        # max age of a killmail in seconds
        max_age = KILLTRACKER_KILLMAIL_MAX_AGE_FOR_TRACKER

    id = factory.Sequence(lambda n: n + 1800000000001)
    victim = factory.SubFactory(KillmailVictimFactory)
    position = factory.SubFactory(KillmailPositionFactory)
    zkb = factory.SubFactory(KillmailZkbFactory)
    solar_system_id = factory.fuzzy.FuzzyChoice(_solar_system_ids)

    @factory.lazy_attribute
    def time(self):
        return factory.fuzzy.FuzzyDateTime(
            now() - dt.timedelta(seconds=self.max_age - 5)
        ).fuzz()

    @factory.lazy_attribute
    def attackers(self):
        amount = factory.fuzzy.FuzzyInteger(1, 10).fuzz()
        my_attackers = [KillmailAttackerFactory() for _ in range(amount)]
        my_attackers[0].is_final_blow = True
        return my_attackers


class WebhookFactory(
    factory.django.DjangoModelFactory, metaclass=BaseMetaFactory[Webhook]
):
    class Meta:
        model = Webhook
        django_get_or_create = ("name",)

    name = factory.Faker("name")
    url = factory.Faker("uri")


class TrackerFactory(
    factory.django.DjangoModelFactory, metaclass=BaseMetaFactory[Tracker]
):
    class Meta:
        model = Tracker
        django_get_or_create = ("name",)

    name = factory.Faker("name")
    webhook = factory.SubFactory(WebhookFactory)


class EveKillmailFactory(
    factory.django.DjangoModelFactory, metaclass=BaseMetaFactory[EveKillmail]
):
    class Meta:
        model = EveKillmail
        django_get_or_create = ("id",)

    class Params:
        # max age of a killmail in seconds
        max_age = KILLTRACKER_KILLMAIL_MAX_AGE_FOR_TRACKER

    id = factory.Sequence(lambda n: n + 9_000_000)

    # victim
    damage_taken = factory.fuzzy.FuzzyInteger(1_000_000)
    character = factory.SubFactory(EveEntityCharacterFactory)
    corporation = factory.SubFactory(EveEntityCorporationFactory)
    alliance = factory.SubFactory(EveEntityAllianceFactory)
    faction = factory.LazyAttribute(random_eve_entity_faction)
    ship_type = factory.LazyAttribute(random_eve_entity_ship_type)

    # location
    solar_system = factory.LazyAttribute(random_eve_entity_solar_system)
    position_x = factory.fuzzy.FuzzyFloat(-10_000, 10_000)
    position_y = factory.fuzzy.FuzzyFloat(-10_000, 10_000)
    position_z = factory.fuzzy.FuzzyFloat(-10_000, 10_000)

    # zkb
    location_id = factory.Sequence(lambda n: n + 60_000_000)
    hash = factory.fuzzy.FuzzyText()
    fitted_value = factory.fuzzy.FuzzyFloat(10_000, 100_000_000)
    total_value = factory.LazyAttribute(lambda o: o.fitted_value)
    zkb_points = factory.fuzzy.FuzzyInteger(1000)
    is_npc = False
    is_solo = False
    is_awox = False

    @factory.lazy_attribute
    def time(self):
        return factory.fuzzy.FuzzyDateTime(
            now() - dt.timedelta(seconds=self.max_age - 5)
        ).fuzz()

    # @factory.lazy_attribute
    # def solar_system(self):
    #     return EveSolarSystem.objects.order_by("?").first()

    # @factory.lazy_attribute
    # def ship_type(self):
    #     return EveEntity.objects.filter(id__in=_ship_type_ids).order_by("?").first()

    @factory.post_generation
    def attackers(self, create, extracted, **kwargs):
        if not create or extracted is False:
            # Simple build, or does not want to create attackers.
            return

        amount = factory.fuzzy.FuzzyInteger(1, 10).fuzz()
        EveKillmailAttackerFactory.create_batch(size=amount - 1, killmail=self)
        EveKillmailAttackerFactory(killmail=self, is_final_blow=True)


class EveKillmailAttackerFactory(
    factory.django.DjangoModelFactory, metaclass=BaseMetaFactory[EveKillmailAttacker]
):
    class Meta:
        model = EveKillmailAttacker

    killmail = factory.SubFactory(EveKillmailFactory, attackers=False)
    character = factory.SubFactory(EveEntityCharacterFactory)
    corporation = factory.SubFactory(EveEntityCorporationFactory)
    alliance = factory.SubFactory(EveEntityAllianceFactory)
    faction = factory.LazyAttribute(random_eve_entity_faction)
    ship_type = factory.LazyAttribute(random_eve_entity_ship_type)
    weapon_type = factory.LazyAttribute(random_eve_entity_weapon_type)

    damage_done = factory.fuzzy.FuzzyInteger(1_000_000)
    security_status = factory.fuzzy.FuzzyFloat(-10.0, 5)
    is_final_blow = False
