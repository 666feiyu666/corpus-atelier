"""Command-line adapter for inspecting saved tasks and managing the corpus."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .app.service import CorpusAtelierApplication
from .config.paths import resolve_paths
from .corpus.gallery import import_seed, load_seed, packaged_seed_path
from .corpus.index import CorpusStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="corpus-atelier")
    commands = parser.add_subparsers(dest="command", required=True)

    inspect = commands.add_parser("inspect", help="Inspect a saved task.")
    inspect.add_argument("run_id")
    inspect.add_argument("--runs-root", type=Path, default=None)

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
    if args.command == "corpus":
        return _import_gallery(args)

    runs_root = args.runs_root or resolve_paths().tasks_root
    app = CorpusAtelierApplication(runs_root=runs_root)
    try:
        run_dir = app.store.find_run(args.run_id)
        print(json.dumps(app.store.manifest(run_dir), ensure_ascii=False, indent=2))
    finally:
        app.close()
    return 0
