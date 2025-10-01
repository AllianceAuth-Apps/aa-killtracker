from unittest.mock import patch

from django.test import TestCase
from django.utils.timezone import now

from killtracker.core.helpers import cache_get_timestamp, cache_set_timestamp
from killtracker.tests.utils import CacheFake

MODULE_PATH = "killtracker.core.helpers"


@patch(MODULE_PATH + ".cache", new_callable=CacheFake)
class TestCacheWithTimestamp(TestCase):
    def test_should_return_value_when_key_found(self, mock_cache):
        value = now()
        cache_set_timestamp("abc", value)
        got = cache_get_timestamp("abc")
        self.assertEqual(got, value)

    def test_should_return_none_when_key_not_found(self, mock_cache):
        fallback = now()
        got = cache_get_timestamp("def", fallback)
        self.assertIsNone(got)

    def test_should_return_fallback_when_key_not_found_2(self, mock_cache):
        got = cache_get_timestamp("abc")
        self.assertIsNone(got)

    def test_should_return_fallback_when_value_fails_to_parse(self, mock_cache):
        fallback = now()
        mock_cache.set("abc", "invalid")
        got = cache_get_timestamp("abc", fallback)
        self.assertEqual(got, fallback)
