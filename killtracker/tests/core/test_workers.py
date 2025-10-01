from unittest.mock import patch

from django.test import TestCase

from killtracker.core import workers
from killtracker.tests.utils import CacheFake

MODULE_PATH = "killtracker.core.workers"


class TaskFake:
    class RequestFake:
        def __init__(self, hostname: str):
            self.hostname = hostname

    def __init__(self, hostname: str):
        self.request = self.RequestFake(hostname)


class TestWorker(TestCase):
    def test_should_report_false_when_not_set(self):
        with patch(MODULE_PATH + ".cache", new_callable=CacheFake):
            got = workers.is_shutting_down("dummy")
        self.assertFalse(got)

    def test_should_report_true_when_set(self):
        with patch(MODULE_PATH + ".cache", new_callable=CacheFake):
            workers.state_set("alpha")
            got = workers.is_shutting_down(TaskFake("alpha"))
        self.assertTrue(got)

    def test_should_report_false_when_other_worker_is_shutting_down(self):
        with patch(MODULE_PATH + ".cache", new_callable=CacheFake):
            workers.state_set("alpha")
            got = workers.is_shutting_down(TaskFake("bravo"))
        self.assertFalse(got)

    def test_should_report_false_when_task_not_valid(self):
        with patch(MODULE_PATH + ".cache", new_callable=CacheFake):
            workers.state_set("alpha")
            got = workers.is_shutting_down("invalid")
        self.assertFalse(got)

    def test_should_report_false_when_worker_shutdown_has_reset(self):
        with patch(MODULE_PATH + ".cache", new_callable=CacheFake):
            workers.state_set("alpha")
            workers.state_reset("alpha")
            got = workers.is_shutting_down(TaskFake("alpha"))
        self.assertFalse(got)
