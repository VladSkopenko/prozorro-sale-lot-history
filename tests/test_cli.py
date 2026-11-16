import csv

from lot_history.chains import assign_lots
from lot_history.cli import main
from lot_history.collector import collect
from lot_history.store import Store
from tests.conftest import FakeSource


def prepared_database(tmp_path, monkeypatch, chain, settings, connect):
    path = tmp_path / "lots.sqlite3"
    store = Store(path)
    collect(connect(FakeSource(chain)), store, settings, since="2026-06-01T00:00:00")
    assign_lots(store)
    store.close()
    monkeypatch.setenv("LOT_HISTORY_DB", str(path))
    # команда читає `.env` з робочого каталогу; власний файл розробника не має потрапити в тест
    monkeypatch.chdir(tmp_path)
    return path


def test_stats_prints_what_the_store_holds(tmp_path, monkeypatch, capsys, chain, settings, connect):
    prepared_database(tmp_path, monkeypatch, chain, settings, connect)

    assert main(["stats"]) == 0

    printed = capsys.readouterr().out
    assert "аукціонів (спроб): 12" in printed
    assert "не відбулося: 7" in printed


def test_export_writes_the_lot_rows_to_a_csv_file(tmp_path, monkeypatch, capsys, chain, settings, connect):
    prepared_database(tmp_path, monkeypatch, chain, settings, connect)
    target = tmp_path / "lots.csv"

    assert main(["export", "--csv", str(target), "--min-attempts", "2"]) == 0

    with target.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["attempts"] for row in rows] == ["12"]


def test_an_airtable_dry_run_sends_nothing_and_needs_no_token(
    tmp_path, monkeypatch, capsys, chain, settings, connect
):
    prepared_database(tmp_path, monkeypatch, chain, settings, connect)
    monkeypatch.delenv("AIRTABLE_TOKEN", raising=False)

    assert main(["export", "--airtable", "--dry-run"]) == 0

    assert "dry run: 1 лотів було б записано в таблицю 'Lots'" in capsys.readouterr().out


def test_an_airtable_sync_without_credentials_stops_with_a_hint(
    tmp_path, monkeypatch, capsys, chain, settings, connect
):
    prepared_database(tmp_path, monkeypatch, chain, settings, connect)
    monkeypatch.delenv("AIRTABLE_TOKEN", raising=False)
    monkeypatch.delenv("AIRTABLE_BASE_ID", raising=False)

    assert main(["export", "--airtable"]) == 2

    assert "AIRTABLE_TOKEN" in capsys.readouterr().err
