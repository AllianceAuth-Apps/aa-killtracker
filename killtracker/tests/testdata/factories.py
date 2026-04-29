import datetime as dt
from typing import Generic, TypeVar

import factory
import factory.fuzzy

from django.db.models import Max
from django.utils.timezone import now
from eveuniverse.models import EveEntity
from eveuniverse.tests.testdata.factories_2 import (
    EveEntityFactory,
    EveSolarSystemFactory,
)

from allianceauth.eveonline.models import EveFactionInfo

from killtracker.app_settings import KILLTRACKER_KILLMAIL_MAX_AGE_FOR_TRACKER
from killtracker.core.zkb import (
    Killmail,
    KillmailAttacker,
    KillmailPosition,
    KillmailVictim,
    KillmailZkb,
    _KillmailCharacter,
)
from killtracker.models import EveKillmail, EveKillmailAttacker, Tracker, Webhook

T = TypeVar("T")


class BaseMetaFactory(Generic[T], factory.base.FactoryMetaClass):
    def __call__(cls, *args, **kwargs) -> T:
        return super().__call__(*args, **kwargs)


class EveEntityAllianceFactory(EveEntityFactory):
    id = factory.Sequence(lambda n: 99_900_001 + n)
    name = factory.Sequence(lambda n: f"alliance_name_{n}")
    category = EveEntity.CATEGORY_ALLIANCE


class EveEntityCharacterFactory(EveEntityFactory):
    pass


class EveEntityCorporationFactory(EveEntityFactory):
    id = factory.Sequence(lambda n: 98_900_001 + n)
    name = factory.Sequence(lambda n: f"corporation_name_{n}")
    category = EveEntity.CATEGORY_CORPORATION


class EveEntityFactionFactory(EveEntityFactory):
    id = factory.Sequence(lambda n: 509_001 + n)
    name = factory.Sequence(lambda n: f"faction_name_{n}")
    category = EveEntity.CATEGORY_FACTION


class EveEntityInventoryTypeFactory(EveEntityFactory):
    id = factory.Sequence(lambda n: 900_001 + n)
    name = factory.Sequence(lambda n: f"inventory_type_{n}")
    category = EveEntity.CATEGORY_INVENTORY_TYPE


class EveEntitySolarSystemFactory(EveEntityFactory):
    id = factory.Sequence(lambda n: 30_990_000 + n)
    name = factory.Sequence(lambda n: f"solar_system_{n}")
    category = EveEntity.CATEGORY_SOLAR_SYSTEM


class EveSolarSystemNullSecFactory(EveSolarSystemFactory):
    security_status = -1.0


class EveSolarSystemLowSecFactory(EveSolarSystemFactory):
    security_status = 0.3


class EveSolarSystemHighSecFactory(EveSolarSystemFactory):
    security_status = 0.9


class EveSolarSystemWSpaceFactory(EveSolarSystemFactory):
    id = factory.Sequence(lambda n: 31_900_000 + n)
    security_status = -1.0


class EveFactionInfoFactory(
    factory.django.DjangoModelFactory, metaclass=BaseMetaFactory[EveFactionInfo]
):
    """Generate an EveFactionInfo object."""

    class Meta:
        model = EveFactionInfo
        django_get_or_create = ("faction_id", "faction_name")

    faction_name = factory.Faker("catch_phrase")

    @factory.lazy_attribute
    def faction_id(self):
        last_id = (
            EveFactionInfo.objects.aggregate(Max("faction_id"))["faction_id__max"]
            or 500_000
        )
        return last_id + 1


class KillmailCharacterFactory(
    factory.Factory, metaclass=BaseMetaFactory[_KillmailCharacter]
):
    class Meta:
        model = _KillmailCharacter

    character_id = factory.LazyAttribute(lambda _: EveEntityCharacterFactory().id)
    corporation_id = factory.LazyAttribute(lambda _: EveEntityCorporationFactory().id)
    alliance_id = factory.LazyAttribute(lambda _: EveEntityAllianceFactory().id)
    ship_type_id = factory.LazyAttribute(lambda _: EveEntityInventoryTypeFactory().id)


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
    weapon_type_id = factory.LazyAttribute(lambda _: EveEntityInventoryTypeFactory().id)


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
        attacker_count = 0
        is_npc = factory.Trait(
            zkb__is_npc=True,
            attackers=factory.LazyAttribute(
                lambda _: [
                    KillmailAttackerFactory(
                        alliance_id=None,
                        corporation_id=None,
                        character_id=None,
                        faction_id=EveEntityFactionFactory().id,
                        weapon_type_id=None,
                        is_final_blow=True,
                    )
                ],
            ),
        )

    id = factory.Sequence(lambda n: n + 1800000000001)
    victim = factory.SubFactory(KillmailVictimFactory)
    position = factory.SubFactory(KillmailPositionFactory)
    zkb = factory.SubFactory(KillmailZkbFactory)

    @factory.lazy_attribute
    def solar_system_id(self):
        o = EveSolarSystemFactory()
        EveEntitySolarSystemFactory(id=o.id)
        return o.id

    @factory.lazy_attribute
    def time(self):
        return factory.fuzzy.FuzzyDateTime(
            now() - dt.timedelta(seconds=self.max_age - 5)
        ).fuzz()

    @factory.lazy_attribute
    def attackers(self):
        if self.attacker_count == 0:
            amount = factory.fuzzy.FuzzyInteger(1, 10).fuzz()
        else:
            amount = self.attacker_count

        my_attackers: list[KillmailAttacker]
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
    ship_type = factory.SubFactory(EveEntityInventoryTypeFactory)

    # location
    solar_system = factory.SubFactory(EveEntitySolarSystemFactory)
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
    ship_type = factory.SubFactory(EveEntityInventoryTypeFactory)
    weapon_type = factory.SubFactory(EveEntityInventoryTypeFactory)

    damage_done = factory.fuzzy.FuzzyInteger(1_000_000)
    security_status = factory.fuzzy.FuzzyFloat(-10.0, 5)
    is_final_blow = False


class R2Z2ResponseFactory(factory.DictFactory, metaclass=BaseMetaFactory[dict]):
    class Meta:
        exclude = ("killmail",)

    killmail = factory.SubFactory(KillmailFactory)  # parameter

    hash = factory.LazyAttribute(lambda o: o.killmail.zkb.hash)
    killmail_id = factory.LazyAttribute(lambda o: o.killmail.id)
    sequence_id = factory.Sequence(lambda n: n + 1_001)
    uploaded_at = factory.LazyAttribute(lambda o: now().timestamp())

    @factory.lazy_attribute
    def esi(self):
        km: Killmail = self.killmail
        victim = km.victim.asdict()
        victim["position"] = km.position.asdict()

        attackers = []
        for a in km.attackers:
            attacker = a.asdict()
            if a.is_final_blow:
                attacker["final_blow"] = True
                del attacker["is_final_blow"]

            attackers.append(attacker)

        d = {
            "attackers": attackers,
            "killmail_id": km.id,
            "killmail_time": km.time.isoformat(),
            "solar_system_id": km.solar_system_id,
            "victim": victim,
        }
        return d

    @factory.lazy_attribute
    def zkb(self):
        z: KillmailZkb = self.killmail.zkb
        d = {
            "locationID": z.location_id,
            "hash": z.hash,
            "fittedValue": z.fitted_value,
            "droppedValue": z.fitted_value,
            "destroyedValue": z.fitted_value,
            "totalValue": z.total_value,
            "points": z.points,
            "npc": z.is_npc,
            "solo": z.is_solo,
            "awox": z.is_awox,
            "labels": [],
            "attackerCount": len(self.killmail.attackers),
            "href": f"https://esi.evetech.net/killmails/{z.hash}/",
        }
        return d
