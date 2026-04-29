"""ESI provider for killtracker."""

from pathlib import Path

from esi.openapi_clients import ESIClientProvider

from . import __version__

spec_file = Path(__file__).parent / "openapi_2025-12-16.json"
esi = ESIClientProvider(
    compatibility_date="2025-12-16",
    ua_appname="aa-killtracker",
    ua_version=__version__,
    operations=[
        "GetKillmailsKillmailIdKillmailHash",
    ],
    spec_file=spec_file,
)
