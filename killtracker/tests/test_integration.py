from unittest.mock import MagicMock, patch

import dhooks_lite
import pook

from django.core.cache import cache
from django.test import TestCase
from django.test.utils import override_settings

from killtracker import tasks

from .testdata.factories import R2Z2ResponseFactory, TrackerFactory

PACKAGE_PATH = "killtracker"


@patch("celery.app.task.Context.called_directly", False)  # make retry work with eager
@override_settings(CELERY_ALWAYS_EAGER=True)
@patch(PACKAGE_PATH + ".tasks.workers.is_shutting_down", lambda x: False)
@patch(PACKAGE_PATH + ".core.discord.dhooks_lite.Webhook.execute", spec=True)
class TestTasksEnd2End(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @pook.on
    def test_normal_case(self, mock_execute: MagicMock):
        # given
        mock_execute.return_value = dhooks_lite.WebhookResponse({}, status_code=200)
        sequence_id = 12345
        pook.get(
            "https://r2z2.zkillboard.com/ephemeral/sequence.json",
            reply=200,
            response_json={"sequence": sequence_id},
        )
        data_1 = R2Z2ResponseFactory(sequence_id=sequence_id)
        pook.get(
            f"https://r2z2.zkillboard.com/ephemeral/{sequence_id}.json",
            reply=200,
            response_json=data_1,
        )
        sequence_id += 1
        data_2 = R2Z2ResponseFactory(sequence_id=sequence_id)
        pook.get(
            f"https://r2z2.zkillboard.com/ephemeral/{sequence_id}.json",
            reply=200,
            response_json=data_2,
        )
        sequence_id += 1
        pook.get(
            f"https://r2z2.zkillboard.com/ephemeral/{sequence_id}.json",
            reply=404,
            response_json={},
        )
        TrackerFactory(name="My Tracker")

        # when
        tasks.run_killtracker.delay()

        # then
        self.assertEqual(mock_execute.call_count, 2)
