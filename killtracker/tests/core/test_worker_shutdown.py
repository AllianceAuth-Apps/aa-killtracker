from unittest.mock import patch

from django.test import TestCase

from killtracker.core.worker_shutdown import is_shutting_down

MODULE_PATH = "killtracker.core.worker_shutdown"


class FakeTask:
    class FakeRequest:
        def __init__(self, hostname: str):
            self.hostname = hostname

    def __init__(self, hostname: str):
        self.request = self.FakeRequest(hostname)


@patch(MODULE_PATH + ".cache")
class TestWorkerShutdown(TestCase):
    def test_should_report_false_when_not_set(self, mock_cache):
        mock_cache.get.return_value = None
        got = is_shutting_down("dummy")
        self.assertFalse(got)

    def test_should_report_true_when_set(self, mock_cache):
        mock_cache.get.return_value = "value"
        got = is_shutting_down(FakeTask("dummy"))
        self.assertTrue(got)

    def test_should_report_false_when_task_not_valid(self, mock_cache):
        mock_cache.get.return_value = "value"
        got = is_shutting_down("invalid")
        self.assertFalse(got)
