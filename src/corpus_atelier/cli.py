"""Command-line adapter for inspecting saved tasks and managing the corpus."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .app.service import CorpusAtelierApplication
from .config.paths import resolve_paths
from .config.ports import PortUnavailable, require_available
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

    api = commands.add_parser(
        "api", help="Serve the local HTTP API for the browser interface.",
    )
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument(
        "--port", type=int, default=None,
        help=(
            "Bind this port (default 8787, or 8788 with --dev). A port that "
            "another program is using stops startup instead of being borrowed "
            "or skipped, so a request can never reach that program."
        ),
    )
    api.add_argument(
        "--dev", action="store_true",
        help=(
            "Serve the development profile: a separate data root (.atelier/dev) "
            "and port 8788, so daily tasks and corpus stay untouched."
        ),
    )
    api.add_argument(
        "--allow-remote", action="store_true",
        help="Permit binding a non-loopback host. The API is local-first by default.",
    )
    api.add_argument(
        "--no-resume", action="store_true",
        help="Do not resume interrupted text steps at startup.",
    )

    start = commands.add_parser(
        "start",
        help="Serve the API and the built interface on one port (daily use).",
    )
    start.add_argument("--host", default="127.0.0.1")
    start.add_argument(
        "--port", type=int, default=8787,
        help=(
            "Bind this port. A port that another program is using stops startup "
            "instead of being borrowed or skipped."
        ),
    )
    start.add_argument(
        "--allow-remote", action="store_true",
        help="Permit binding a non-loopback host. The product is local-first.",
    )
    start.add_argument(
        "--no-resume", action="store_true",
        help="Do not resume interrupted text steps at startup.",
    )
    return parser


LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _require_port(host: str, port: int, purpose: str) -> None:
    """Stop before binding a port that already belongs to another program."""
    try:
        require_available(host, port, purpose=purpose)
    except PortUnavailable as error:
        raise SystemExit(str(error)) from None


def _serve_api(args) -> int:
    """Serve the HTTP boundary over loopback only, unless told otherwise."""
    if args.host not in LOOPBACK_HOSTS and not args.allow_remote:
        raise SystemExit(
            f"Refusing to bind {args.host!r}: this API is local-only. "
            "Pass --allow-remote to expose it deliberately."
        )
    if args.dev:
        # Set before anything resolves paths: the profile decides the data root.
        os.environ["CORPUS_ATELIER_PROFILE"] = "dev"
    port = args.port if args.port is not None else (8788 if args.dev else 8787)
    _require_port(args.host, port, "the API")

    import uvicorn

    from .api import TaskRuntime, create_app

    paths = resolve_paths()
    print(
        f"profile: {'dev' if args.dev else 'daily'} · data: {paths.tasks_root.parent} "
        f"· listening on http://{args.host}:{port}",
        flush=True,
    )
    app = create_app(runtime=TaskRuntime(paths=paths), resume=not args.no_resume)
    uvicorn.run(app, host=args.host, port=int(port), log_level="info")
    return 0


def _serve_start(args) -> int:
    """Serve the API and the built interface together: one process, one port."""
    if args.host not in LOOPBACK_HOSTS and not args.allow_remote:
        raise SystemExit(
            f"Refusing to bind {args.host!r}: this product is local-only. "
            "Pass --allow-remote to expose it deliberately."
        )
    import uvicorn

    from .api import TaskRuntime, create_app
    from .api.app import interface_directory

    _require_port(args.host, args.port, "the interface and API")

    paths = resolve_paths()
    interface = interface_directory()
    if interface is None:
        print(
            "interface not built yet: run `cd web && npm install && npm run build`.\n"
            "Serving the API only for now.",
            flush=True,
        )
    print(
        f"profile: daily · data: {paths.tasks_root.parent} "
        f"· http://{args.host}:{args.port}",
        flush=True,
    )
    app = create_app(
        runtime=TaskRuntime(paths=paths),
        resume=not args.no_resume,
        interface_dir=interface,
    )
    uvicorn.run(app, host=args.host, port=int(args.port), log_level="info")
    return 0


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
    if args.command == "api":
        return _serve_api(args)
    if args.command == "start":
        return _serve_start(args)

    runs_root = args.runs_root or resolve_paths().tasks_root
    app = CorpusAtelierApplication(runs_root=runs_root)
    try:
        run_dir = app.store.find_run(args.run_id)
        print(json.dumps(app.store.manifest(run_dir), ensure_ascii=False, indent=2))
    finally:
        app.close()
    return 0
