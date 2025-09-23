from django.apps import AppConfig

from . import __version__


class KillmailsConfig(AppConfig):
    name = "killtracker"
    label = "killtracker"
    verbose_name = f"Killtracker v{__version__}"

    def ready(self) -> None:
        from . import checks  # noqa: F401 pylint: disable=unused-import
        from .core.killmails import Killmail

        Killmail.reset_lock_key()
