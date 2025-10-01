from unittest.mock import patch

import dhooks_lite
import requests_mock

from django.core.cache import cache
from django.test.utils import override_settings

from app_utils.testing import NoSocketsTestCase

from killtracker import tasks
from killtracker.core.zkb import _ZKB_REDISQ_URL

from .testdata.factories import TrackerFactory, WebhookFactory
from .testdata.helpers import (
    killmails_data,
    load_eve_corporations,
    load_eve_entities,
    load_eveuniverse,
)

PACKAGE_PATH = "killtracker"


@patch("celery.app.task.Context.called_directly", False)  # make retry work with eager
@override_settings(CELERY_ALWAYS_EAGER=True)
@patch(PACKAGE_PATH + ".core.zkb.KILLTRACKER_QUEUE_ID", "dummy")
@patch(PACKAGE_PATH + ".tasks.workers.is_shutting_down", lambda x: False)
@patch(PACKAGE_PATH + ".tasks.is_esi_online", lambda: True)
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

    @patch(PACKAGE_PATH + ".tasks.retry_task_if_esi_is_down", lambda x: None)
    def test_normal_case(self, requests_mocker, mock_execute):
        # given
        mock_execute.return_value = dhooks_lite.WebhookResponse({}, status_code=200)
        requests_mocker.register_uri(
            "GET",
            _ZKB_REDISQ_URL,
            [
                {"status_code": 200, "json": {"package": killmails_data()[10000001]}},
                {"status_code": 200, "json": {"package": killmails_data()[10000002]}},
                {"status_code": 200, "json": {"package": killmails_data()[10000003]}},
                {"status_code": 200, "json": {"package": None}},
            ],
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

    @patch(PACKAGE_PATH + ".tasks.retry_task_if_esi_is_down")
    def test_should_retry_when_esi_error_limit_reached(
        self, requests_mocker, mock_retry_task_if_esi_is_down, mock_execute
    ):
        def my_retry_task_if_esi_is_down(task):
            """Retry the task one time only."""
            if task.request.retries < 1:
                raise task.retry()

        # given
        mock_execute.return_value = dhooks_lite.WebhookResponse({}, status_code=200)
        mock_retry_task_if_esi_is_down.side_effect = my_retry_task_if_esi_is_down
        requests_mocker.register_uri(
            "GET",
            _ZKB_REDISQ_URL,
            [
                {"status_code": 200, "json": {"package": killmails_data()[10000001]}},
                {"status_code": 200, "json": {"package": None}},
            ],
        )
        # when
        tasks.run_killtracker.delay()
        # then
        self.assertEqual(mock_execute.call_count, 1)
