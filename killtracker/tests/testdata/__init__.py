from pathlib import Path

_current_dir = Path(__file__).parent
_FILENAME_EVEUNIVERSE_TESTDATA = "eveuniverse.json"


def test_data_filename() -> str:
    return str(_current_dir / _FILENAME_EVEUNIVERSE_TESTDATA)
