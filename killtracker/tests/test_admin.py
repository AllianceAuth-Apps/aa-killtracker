from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django_webtest import WebTest

from allianceauth.eveonline.models import EveCorporationInfo
from app_utils.testdata_factories import UserFactory

from killtracker.models import Tracker, Webhook

from .testdata.factories import TrackerFactory, WebhookFactory
from .testdata.helpers import LoadTestDataMixin


class TestTrackerChangeList(LoadTestDataMixin, WebTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = User.objects.create_superuser(
            "Bruce_Wayne", "bruce@example.com", "password"
        )

    def setUp(self) -> None:
        TrackerFactory(webhook=self.webhook_1, exclude_high_sec=True)
        TrackerFactory(
            webhook=self.webhook_1,
            origin_solar_system_id=30003067,
            require_max_jumps=3,
        )
        tracker = TrackerFactory(webhook=self.webhook_1)
        tracker.exclude_attacker_corporations.add(
            EveCorporationInfo.objects.get(corporation_id=2001)
        )

    def test_can_open_page_normally(self):
        # login
        self.app.set_user(self.user)

        # user tries to add new notification rule
        add_page = self.app.get(reverse("admin:killtracker_tracker_changelist"))
        self.assertEqual(add_page.status_code, 200)


class TestTrackerValidations(LoadTestDataMixin, WebTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.webhook = Webhook.objects.create(name="Dummy", url="http://www.example.com")
        cls.user = User.objects.create_superuser(
            "Bruce_Wayne", "bruce@example.com", "password"
        )
        cls.url_add = reverse("admin:killtracker_tracker_add")
        cls.url_changelist = reverse("admin:killtracker_tracker_changelist")

    def setUp(self) -> None:
        Tracker.objects.all().delete()

    def _open_page(self) -> object:
        # login
        self.app.set_user(self.user)

        # user tries to add new notification rule
        add_page = self.app.get(self.url_add)
        self.assertEqual(add_page.status_code, 200)
        form = add_page.forms["tracker_form"]
        form["name"] = "Test Tracker"
        form["webhook"] = self.webhook_1.pk
        return form

    def test_no_errors(self):
        form = self._open_page()
        response = form.submit()

        # assert results
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.url_changelist)
        self.assertEqual(Tracker.objects.count(), 1)

    def test_can_not_have_require_max_jumps_without_origin(self):
        form = self._open_page()
        form["require_max_jumps"] = 10
        response = form.submit()

        # assert results
        self.assertEqual(response.status_code, 200)
        self.assertIn("Please correct the error below", response.text)
        self.assertEqual(Tracker.objects.count(), 0)

    def test_can_not_have_require_max_distance_without_origin(self):
        form = self._open_page()
        form["require_max_distance"] = 5
        response = form.submit()

        # assert results
        self.assertEqual(response.status_code, 200)
        self.assertIn("Please correct the error below", response.text)
        self.assertEqual(Tracker.objects.count(), 0)

    def test_min_attackers_must_be_less_than_max_attackers(self):
        form = self._open_page()
        form["require_min_attackers"] = 10
        form["require_max_attackers"] = 5
        response = form.submit()

        # assert results
        self.assertEqual(response.status_code, 200)
        self.assertIn("Please correct the error below", response.text)
        self.assertEqual(Tracker.objects.count(), 0)

    def test_can_not_exclude_all_space_types(self):
        form = self._open_page()
        form["exclude_high_sec"] = True
        form["exclude_low_sec"] = True
        form["exclude_null_sec"] = True
        form["exclude_w_space"] = True
        response = form.submit()

        # assert results
        self.assertEqual(response.status_code, 200)
        self.assertIn("Please correct the error below", response.text)
        self.assertEqual(Tracker.objects.count(), 0)

    def test_can_both_exclude_and_require_npc_kills(self):
        form = self._open_page()
        form["exclude_npc_kills"] = True
        form["require_npc_kills"] = True
        response = form.submit()

        # assert results
        self.assertEqual(response.status_code, 200)
        self.assertIn("Please correct the error below", response.text)
        self.assertEqual(Tracker.objects.count(), 0)


class TestTrackerValidations2(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = UserFactory(is_staff=True, is_superuser=True)
        cls.webhook = WebhookFactory()
        cls.url_add = reverse("admin:killtracker_tracker_add")
        cls.url_changelist = reverse("admin:killtracker_tracker_changelist")

    def test_should_add_new_tracker(self):
        # given
        self.client.force_login(self.user)
        data = {
            "name": "Dummy",
            "webhook": self.webhook.pk,
            "_save": "Save",
            "is_enabled": "on",
            "color": "#000000",
            "ping_type": "PN",
            "is_posting_name": "on",
        }

        # when
        response = self.client.post(self.url_add, data=data)

        # then
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.url_changelist)
        self.assertTrue(Tracker.objects.filter(name="Dummy").exists())
