"""Command-line adapter for validating and inspecting saved Corpus Atelier tasks.

Generation lives in the chat studio (Streamlit); the CLI is intentionally
read-only so there is a single generation path.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .app.service import CorpusAtelierApplication
from .config.paths import resolve_paths
from .corpus.gallery import import_seed, load_seed, packaged_seed_path
from .corpus.index import CorpusStore
from .design_support.validation import validate
from .app.registry import PROFILES, get_profile


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="corpus-atelier")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("profiles", help="List registered design profiles.")

    validate_cmd = commands.add_parser(
        "validate", help="Validate inputs without model calls.",
    )
    validate_cmd.add_argument("--profile", required=True, choices=PROFILES)
    validate_cmd.add_argument("--brief", required=True, type=Path)

    inspect = commands.add_parser("inspect", help="Inspect a saved task.")
    inspect.add_argument("run_id")
    inspect.add_argument("--case-id", required=True)
    inspect.add_argument("--runs-root", type=Path, default=Path(".atelier/tasks"))

    corpus = commands.add_parser("corpus", help="Manage the local corpus archive.")
    corpus_commands = corpus.add_subparsers(dest="corpus_command", required=True)
    gallery = corpus_commands.add_parser(
        "import-gallery",
        help="Archive the packaged GPT-Image2-Skill gallery into the local corpus.",
    )
    gallery.add_argument(
        "--source", required=True, type=Path,
        help="Upstream GPT-Image2-Skill checkout that still holds the gallery images.",
    )
    gallery.add_argument("--seed", type=Path, default=None)
    gallery.add_argument("--db", type=Path, default=None)
    gallery.add_argument("--media-root", type=Path, default=None)
    return parser


def _read_object(path: Path, label: str) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object.")
    return value


def _import_gallery(args) -> int:
    """Archive the packaged gallery, copying its images from the given checkout."""
    source = Path(args.source)
    if not source.is_dir():
        raise SystemExit(f"--source is not a directory: {source}")
    paths = resolve_paths()
    db_path = Path(args.db) if args.db else paths.corpus_db_path
    media_root = Path(args.media_root) if args.media_root else paths.corpus_media_root
    seed = load_seed(args.seed or packaged_seed_path())
    db_path.parent.mkdir(parents=True, exist_ok=True)
    media_root.mkdir(parents=True, exist_ok=True)
    store = CorpusStore(db_path)
    try:
        report = import_seed(store, seed, media_root=media_root, source_root=source)
    finally:
        store.close()
    print(f"Gallery seed: {report.imported}/{report.total} records archived.")
    print(f"Images copied into the media root: {report.copied_media}.")
    if report.missing_media:
        preview = ", ".join(report.missing_media[:5])
        more = " …" if len(report.missing_media) > 5 else ""
        print(f"Images missing under --source ({len(report.missing_media)}): {preview}{more}")
    if report.entries_without_image:
        print(f"Entries with no upstream image: {', '.join(report.entries_without_image)}")
    return 0


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "profiles":
        for profile in PROFILES.values():
            print(f"{profile.name}\t{profile.description}")
        return 0

    if args.command == "validate":
        profile = get_profile(args.profile)
        validate(_read_object(args.brief, "Brief"), profile.brief_schema)
        print(f"Valid {profile.name} brief: {args.brief.resolve()}")
        return 0

    if args.command == "corpus":
        return _import_gallery(args)

    app = CorpusAtelierApplication(
        runs_root=getattr(args, "runs_root", ".atelier/tasks"),
    )
    try:
        summary = app.inspect(args.case_id, args.run_id)
        print(json.dumps(summary.manifest, ensure_ascii=False, indent=2))
    finally:
        app.close()
    return 0
