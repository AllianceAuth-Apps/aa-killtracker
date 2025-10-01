from unittest import TestCase

from .utils import CacheFake


class TestCacheFake(TestCase):
    def test_get_should_return_value_when_found(self):
        cache = CacheFake()
        cache.set("alpha", 5)
        got = cache.get("alpha")
        self.assertEqual(got, 5)

    def test_get_should_return_default_when_not_found(self):
        cache = CacheFake()
        cache.set("alpha", 5)
        got = cache.get("bravo", 99)
        self.assertEqual(got, 99)

    def test_delete_should_remove_key(self):
        cache = CacheFake()
        cache.set("alpha", 5)
        cache.delete("alpha")
        self.assertIsNone(cache.get("alpha"))

    def test_delete_should_ignore_when_key_does_not_exist(self):
        cache = CacheFake()
        cache.delete("alpha")

    def test_clear_should_remove_all_keys(self):
        cache = CacheFake()
        cache.set("alpha", 5)
        cache.clear()
        self.assertIsNone(cache.get("alpha"))

    def test_set_with_timeout(self):
        cache = CacheFake()
        cache.set("alpha", "django", timeout=5)
        got = cache.get("alpha")
        self.assertEqual(got, "django")
