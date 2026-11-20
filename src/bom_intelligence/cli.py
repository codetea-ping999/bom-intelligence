"""Command-line entrypoint (``bom``)."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from bom_intelligence import __version__


def _cmd_scan(args: argparse.Namespace) -> int:
    from bom_intelligence.scanner import (
        scan_directory,
        write_inventory_csv,
        write_inventory_jsonl,
    )

    entries = scan_directory(Path(args.root))
    write_inventory_jsonl(entries, Path(args.output))
    if args.csv:
        write_inventory_csv(entries, Path(args.csv))
    types = Counter(e.document_type.value for e in entries)
    dups = sum(1 for e in entries if e.duplicate_group)
    errors = sum(1 for e in entries if e.error)
    print(
        f"scanned {len(entries)} files "
        f"({', '.join(f'{k}={v}' for k, v in sorted(types.items()))}); "
        f"{dups} in duplicate groups; {errors} unreadable -> {args.output}"
    )
    return 0


def _cmd_profile(args: argparse.Namespace) -> int:
    from bom_intelligence.analyzer import diagnose_excel, diagnose_powerpoint
    from bom_intelligence.models import DocumentType, document_type_for_suffix
    from bom_intelligence.profiler import profile_excel, profile_powerpoint
    from bom_intelligence.vocabulary import Vocabulary

    path = Path(args.file)
    vocab = Vocabulary.load(Path(args.aliases)) if args.aliases else None
    doc_type = document_type_for_suffix(path.suffix)
    if doc_type in (DocumentType.XLSX, DocumentType.XLSM):
        excel = profile_excel(path, vocabulary=vocab)
        payload = {
            "profile": excel.model_dump(mode="json"),
            "diagnostics": [d.model_dump(mode="json") for d in diagnose_excel(excel)],
        }
    elif doc_type is DocumentType.PPTX:
        ppt = profile_powerpoint(path, vocabulary=vocab)
        payload = {
            "profile": ppt.model_dump(mode="json"),
            "diagnostics": [d.model_dump(mode="json") for d in diagnose_powerpoint(ppt)],
        }
    else:
        print(f"no profiler for {doc_type.value} files", file=sys.stderr)
        return 2
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


def _cmd_fixtures(args: argparse.Namespace) -> int:
    from bom_intelligence.synthetic import build_fixtures

    paths = build_fixtures(Path(args.output))
    print(f"wrote {len(paths)} synthetic fixtures to {args.output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bom",
        description="Explainable BOM document intelligence.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    scan = sub.add_parser("scan", help="inventory a directory of documents (read-only)")
    scan.add_argument("root", help="directory to scan recursively")
    scan.add_argument("--output", "-o", default="reports/inventory.jsonl", help="JSONL output")
    scan.add_argument("--csv", help="optional CSV output for spreadsheet analysis")
    scan.set_defaults(func=_cmd_scan)

    profile = sub.add_parser("profile", help="profile one Excel/PowerPoint file")
    profile.add_argument("file")
    profile.add_argument("--output", "-o", help="write JSON here instead of stdout")
    profile.add_argument("--aliases", help="custom alias JSON (see data/aliases.json)")
    profile.set_defaults(func=_cmd_profile)

    fixtures = sub.add_parser("fixtures", help="generate synthetic fixture documents")
    fixtures.add_argument("output", help="directory to write fixtures into")
    fixtures.set_defaults(func=_cmd_fixtures)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
