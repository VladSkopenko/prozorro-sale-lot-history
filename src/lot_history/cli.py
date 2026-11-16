"""Командний рядок: collect, chains, export, verify, stats."""

import argparse
import logging
import sys
from pathlib import Path

from lot_history.airtable import AirtableClient, to_fields
from lot_history.chains import assign_lots, backfill_previous
from lot_history.client import ProzorroSaleClient
from lot_history.collector import DEFAULT_KINDS, collect
from lot_history.config import Settings, load_env_file
from lot_history.export import lot_summaries, write_csv
from lot_history.store import Store
from lot_history.verify import verify

STAT_LABELS = {
    "versions": "версій процедур",
    "attempts": "аукціонів (спроб)",
    "lots": "лотів",
    "unsuccessful": "не відбулося",
    "cancelled": "скасовано",
    "repeated": "повторних торгів",
    "unresolved_previous": "попередніх аукціонів не знайдено в джерелі",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lot-history", description="Історія лотів Prozorro.Продажі")
    commands = parser.add_subparsers(dest="command", required=True)

    collect_cmd = commands.add_parser("collect", help="прочитати стрічку змін від збереженого курсора")
    collect_cmd.add_argument("--since", help="почати звідси, а не з курсора, напр. 2026-11-01T00:00:00")
    collect_cmd.add_argument("--max-pages", type=int, help="зупинитися після стількох сторінок стрічки")
    collect_cmd.add_argument(
        "--all-kinds", action="store_true", help="зберігати всі об'єкти, а не лише нерухомість і землю"
    )

    chains_cmd = commands.add_parser("chains", help="дозібрати попередні аукціони і звести спроби в лоти")
    chains_cmd.add_argument("--max-fetches", type=int, default=500, help="ліміт запитів за один запуск")

    export_cmd = commands.add_parser("export", help="один рядок на лот: у CSV або в Airtable")
    export_cmd.add_argument("--csv", type=Path, help="записати рядки в цей файл")
    export_cmd.add_argument("--airtable", action="store_true", help="upsert рядків у таблицю Airtable")
    export_cmd.add_argument(
        "--dry-run", action="store_true", help="з --airtable: показати, що буде надіслано"
    )
    export_cmd.add_argument("--kind", action="append", choices=["real_estate", "land", "other"])
    export_cmd.add_argument("--min-attempts", type=int, default=1, help="лише лоти з такою кількістю торгів")

    verify_cmd = commands.add_parser("verify", help="звірити збережений аукціон із джерелом")
    verify_cmd.add_argument("auction_id")

    commands.add_parser("stats", help="що лежить у сховищі")
    return parser


def _collect(args: argparse.Namespace, settings: Settings, store: Store) -> int:
    client = ProzorroSaleClient(settings)
    stats = collect(
        client,
        store,
        settings,
        since=args.since,
        max_pages=args.max_pages,
        kinds=None if args.all_kinds else DEFAULT_KINDS,
    )
    print(
        f"сторінок {stats.pages}, записів {stats.seen}: нових аукціонів {stats.new_attempts}, "
        f"змінених {stats.changed_attempts}, без змін {stats.unchanged_attempts}, "
        f"уже збережених {stats.duplicate_versions}, інших типів пропущено {stats.skipped_kind}"
    )
    for problem in stats.invalid:
        print(f"пропущено зіпсований запис: {problem}", file=sys.stderr)
    return 1 if stats.invalid else 0


def _chains(args: argparse.Namespace, settings: Settings, store: Store) -> int:
    fetched, unresolved = backfill_previous(ProzorroSaleClient(settings), store, settings, args.max_fetches)
    lots = assign_lots(store)
    left = len(store.missing_previous())
    print(f"дозібрано попередніх аукціонів {fetched}, не знайдено в джерелі {unresolved}, лотів {lots}")
    if left:
        print(f"ще {left} ланцюжків неповні: запустіть `chains` знову перед експортом", file=sys.stderr)
    return 0


def _export(args: argparse.Namespace, settings: Settings, store: Store) -> int:
    if store.missing_previous():
        print(
            "частина ланцюжків неповна: спершу `chains`, інакше ключі лотів можуть змінитися", file=sys.stderr
        )
    summaries = lot_summaries(store, kinds=args.kind, min_attempts=args.min_attempts)
    if args.csv:
        write_csv(summaries, args.csv)
        print(f"{len(summaries)} лотів записано в {args.csv}")
    if args.airtable and args.dry_run:
        for summary in summaries[:3]:
            print(to_fields(summary))
        print(f"dry run: {len(summaries)} лотів було б записано в таблицю {settings.airtable_table!r}")
    elif args.airtable:
        if not settings.airtable_token or not settings.airtable_base_id:
            print("задайте AIRTABLE_TOKEN і AIRTABLE_BASE_ID або додайте --dry-run", file=sys.stderr)
            return 2
        airtable = AirtableClient(settings.airtable_token, settings.airtable_base_id, settings.airtable_table)
        if airtable.ensure_table():
            print(f"створено таблицю {settings.airtable_table!r}")
        result = airtable.upsert(summaries)
        print(f"Airtable: створено {result.created}, оновлено {result.updated}")
    if not args.csv and not args.airtable:
        print(f"{len(summaries)} лотів; додайте --csv ШЛЯХ або --airtable")
    return 0


def _verify(args: argparse.Namespace, settings: Settings, store: Store) -> int:
    result = verify(ProzorroSaleClient(settings), store, settings, args.auction_id)
    if not result.found_in_store:
        print(f"{args.auction_id} немає у сховищі")
        return 2
    if not result.found_at_source:
        print(f"{args.auction_id} більше немає в джерелі")
        return 1
    print(f"сторінка лота: {result.source_page_url}")
    print(f"у сховищі станом на {result.stored_modified}, у джерелі {result.source_modified}")
    if result.matches:
        print("збігається з джерелом")
        return 0
    for difference in result.differences:
        print(f"{difference.field}: у сховищі {difference.stored!r}, у джерелі {difference.source!r}")
    return 1


def _stats(args: argparse.Namespace, settings: Settings, store: Store) -> int:
    for name, count in store.counts().items():
        print(f"{STAT_LABELS[name]}: {count}")
    return 0


HANDLERS = {"collect": _collect, "chains": _chains, "export": _export, "verify": _verify, "stats": _stats}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    args = _parser().parse_args(argv)
    load_env_file()
    settings = Settings.from_env()
    store = Store(settings.db_path)
    try:
        return HANDLERS[args.command](args, settings, store)
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
