import logging

from django.core.cache import cache
from django.core.management.base import BaseCommand

from app_utils.logging import LoggerAddTag

from killtracker import __title__

logger = LoggerAddTag(logging.getLogger(__name__), __title__)


class Command(BaseCommand):
    help = "Deletes all cache keys from django-esi."

    def handle(self, *args, **options):
        answer = input(
            "Are you sure you want to purge all cache keys from django-esi (y/N)?"
        )
        if answer.lower() != "y":
            self.stdout.write("Aborted by user request.")
            exit(1)

        self.stdout.write("Deleting cache keys...")
        total = cache.delete_pattern("esi_*", itersize=100_000)
        self.stdout.write(f"Deleted {total} keys")
