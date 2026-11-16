import os

import pytest

from lot_history.config import Settings, load_env_file

ENV_FILE = """\
# comment

AIRTABLE_BASE_ID=appFromFile
AIRTABLE_TABLE="Quoted name"
LOT_HISTORY_DELAY=2
not a pair
"""


@pytest.fixture
def environment(monkeypatch) -> dict[str, str]:
    """Власне порожнє оточення, щоб завантажене тестом не потрапило в наступний."""
    isolated: dict[str, str] = {}
    monkeypatch.setattr(os, "environ", isolated)
    return isolated


def test_the_env_file_fills_only_what_the_environment_does_not_set(tmp_path, environment):
    env_file = tmp_path / ".env"
    env_file.write_text(ENV_FILE, encoding="utf-8")
    environment["AIRTABLE_BASE_ID"] = "appFromShell"

    load_env_file(env_file)
    settings = Settings.from_env()

    assert settings.airtable_base_id == "appFromShell"
    assert settings.airtable_table == "Quoted name"
    assert settings.request_delay == 2.0


def test_a_missing_env_file_and_empty_values_fall_back_to_defaults(tmp_path, environment):
    environment["AIRTABLE_TOKEN"] = ""
    environment["AIRTABLE_TABLE"] = ""

    load_env_file(tmp_path / "absent.env")
    settings = Settings.from_env()

    assert settings.airtable_token is None
    assert settings.airtable_table == "Lots"
    assert str(settings.db_path) == "data/lots.sqlite3"
