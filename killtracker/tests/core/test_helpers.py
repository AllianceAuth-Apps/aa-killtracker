import datetime as dt
from typing import Any, NamedTuple, Optional
from unittest import TestCase

from killtracker.core.helpers import datetime_or_none


class TestDatetimeOrNone(TestCase):
    def test_should_return_value(self):
        class Case(NamedTuple):
            value: Any
            want: Optional[dt.datetime]

        now = dt.datetime.now()
        cases = [
            Case(now, now),
            Case("abc", None),
            Case(42, None),
            Case(None, None),
        ]
        for tc in cases:
            got = datetime_or_none(tc.value)
            self.assertIs(got, tc.want)
