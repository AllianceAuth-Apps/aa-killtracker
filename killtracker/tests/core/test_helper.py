from unittest.mock import patch

from django.test import TestCase
from django.utils.timezone import now

from killtracker.core.helper import cache_get_timestamp

MODULE_PATH = "killtracker.core.helper"


@patch(MODULE_PATH + ".cache")
class TestCacheGetTimestamp(TestCase):
    def test_should_return_none_when_key_not_found(self, mock_cache):
        mock_cache.get.return_value = None
        got = cache_get_timestamp("abc", now())
        self.assertIsNone(got)

    def test_should_return_value_when_key_found(self, mock_cache):
        x = now()
        mock_cache.get.return_value = x.isoformat()
        got = cache_get_timestamp("abc", None)
        self.assertEqual(got, x)

    def test_should_return_fallback_when_value_fails_to_parse(self, mock_cache):
        x = now()
        mock_cache.get.return_value = "invalid"
        got = cache_get_timestamp("abc", x)
        self.assertEqual(got, x)
