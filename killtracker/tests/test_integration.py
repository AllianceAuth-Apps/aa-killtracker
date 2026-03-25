from unittest.mock import patch

import dhooks_lite
import requests_mock

from django.core.cache import cache
from django.test.utils import override_settings

from app_utils.testing import NoSocketsTestCase

from killtracker import tasks

from .testdata.factories import TrackerFactory, WebhookFactory
from .testdata.helpers import (
    load_eve_corporations,
    load_eve_entities,
    load_eveuniverse,
    r2z2_data,
)

PACKAGE_PATH = "killtracker"


@patch("celery.app.task.Context.called_directly", False)  # make retry work with eager
@override_settings(CELERY_ALWAYS_EAGER=True)
@patch(PACKAGE_PATH + ".tasks.workers.is_shutting_down", lambda x: False)
@patch(PACKAGE_PATH + ".core.discord.dhooks_lite.Webhook.execute", spec=True)
@requests_mock.Mocker()
class TestTasksEnd2End(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        load_eveuniverse()
        load_eve_corporations()
        load_eve_entities()
        cls.webhook = WebhookFactory()
        cls.tracker = TrackerFactory(
            name="My Tracker",
            exclude_null_sec=True,
            exclude_w_space=True,
            webhook=cls.webhook,
        )

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_normal_case(self, mock_execute, requests_mocker):
        # given
        mock_execute.return_value = dhooks_lite.WebhookResponse({}, status_code=200)
        requests_mocker.register_uri(
            "GET",
            "https://r2z2.zkillboard.com/ephemeral/sequence.json",
            status_code=200,
            json={"sequence": 12345},
        )
        killmails = r2z2_data()
        requests_mocker.register_uri(
            "GET",
            "https://r2z2.zkillboard.com/ephemeral/12345.json",
            status_code=200,
            json=killmails[10000001],
        )
        requests_mocker.register_uri(
            "GET",
            "https://r2z2.zkillboard.com/ephemeral/12346.json",
            status_code=200,
            json=killmails[10000002],
        )
        requests_mocker.register_uri(
            "GET",
            "https://r2z2.zkillboard.com/ephemeral/12347.json",
            status_code=404,
            json={},
        )

        # when
        tasks.run_killtracker.delay()

        # then
        self.assertEqual(mock_execute.call_count, 2)
        _, kwargs = mock_execute.call_args_list[0]
        self.assertIn("My Tracker", kwargs["content"])
        self.assertIn("10000001", kwargs["embeds"][0].url)
        _, kwargs = mock_execute.call_args_list[1]
        self.assertIn("My Tracker", kwargs["content"])
        self.assertIn("10000002", kwargs["embeds"][0].url)
        self.assertIn("10000002", kwargs["embeds"][0].url)
