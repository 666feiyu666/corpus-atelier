"""Command-line adapter for validating and inspecting saved Corpus Atelier tasks.

Generation lives in the chat studio (Streamlit); the CLI is intentionally
read-only so there is a single generation path.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .application import CorpusAtelierApplication
from .design_support.validation import validate
from .registry import PROFILES, get_profile


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
    return parser


def _read_object(path: Path, label: str) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object.")
    return value


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

    app = CorpusAtelierApplication(
        runs_root=getattr(args, "runs_root", ".atelier/tasks"),
    )
    try:
        summary = app.inspect(args.case_id, args.run_id)
        print(json.dumps(summary.manifest, ensure_ascii=False, indent=2))
    finally:
        app.close()
    return 0
