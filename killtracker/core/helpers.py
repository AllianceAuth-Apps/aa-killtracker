"""Helper functions for core modules."""

import datetime as dt
from typing import Any, Optional


def datetime_or_none(v: Any) -> Optional[dt.datetime]:
    """Returns as datetime when it is a datetime else returns None."""
    if v is None:
        return None
    if not isinstance(v, dt.datetime):
        return None
    return v
