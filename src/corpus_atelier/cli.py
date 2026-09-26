"""Command-line adapter for reproducible Corpus Atelier experiments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from .application import CorpusAtelierApplication
from .design_support.validation import validate
from .registry import PROFILES, get_profile
from .state import CandidateSelection, DesignJob, HumanDecision, NaturalLanguageDesignJob


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="corpus-atelier")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("profiles", help="List registered design profiles.")

    validate_cmd = commands.add_parser("validate", help="Validate inputs without model calls.")
    validate_cmd.add_argument("--profile", required=True, choices=PROFILES)
    validate_cmd.add_argument("--brief", required=True, type=Path)

    run = commands.add_parser("run", help="Run one approval-gated design experiment.")
    run.add_argument("--case-id", required=True)
    run.add_argument("--profile", required=True, choices=PROFILES)
    run.add_argument("--brief", required=True, type=Path)
    run.add_argument("--candidates", type=int, choices=(1, 2, 3), default=1)

    request = commands.add_parser(
        "request", help="Run one experiment from an informal design request.",
    )
    request.add_argument("--case-id", default="natural-language")
    request.add_argument(
        "--profile",
        choices=("rhetoric-graphic", "art-graphic"),
        default="rhetoric-graphic",
    )
    source = request.add_mutually_exclusive_group(required=True)
    source.add_argument("--text")
    source.add_argument("--request-file", type=Path)
    request.add_argument("--candidates", type=int, choices=(1, 2, 3), default=1)

    inspect = commands.add_parser("inspect", help="Inspect a saved experiment.")
    inspect.add_argument("run_id")
    inspect.add_argument("--case-id", required=True)
    inspect.add_argument("--runs-root", type=Path, default=Path("experiments/runs"))
    return parser


def _read_object(path: Path, label: str) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object.")
    return value


def _print_result(result) -> None:
    print(f"Run: {result.run_id}")
    print(f"Status: {result.status}")
    print(result.message)
    for name, path in result.artifacts.items():
        print(f"{name}: {path}")


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
        runs_root=getattr(args, "runs_root", "experiments/runs"),
    )
    if args.command == "inspect":
        summary = app.inspect(args.case_id, args.run_id)
        print(json.dumps(summary.manifest, ensure_ascii=False, indent=2))
        return 0

    load_dotenv()
    if args.command == "request":
        request_text = (
            args.text
            if args.text is not None
            else args.request_file.read_text(encoding="utf-8")
        )
        result = app.start_request(NaturalLanguageDesignJob(
            case_id=args.case_id,
            profile=args.profile,
            request=request_text,
            candidate_count=args.candidates,
        ))
    else:
        result = app.start(DesignJob(
            case_id=args.case_id,
            profile=args.profile,
            brief=_read_object(args.brief, "Brief"),
            candidate_count=args.candidates,
        ))
    while True:
        _print_result(result)
        if result.status == "awaiting_approval":
            answer = input(
                "Send this exact request to the image model? [y/N] "
            ).strip().lower()
            note = (
                input("Confirmation note (optional): ").strip()
                if answer in {"y", "yes"}
                else ""
            )
            result = app.resume(result.run_id, HumanDecision(
                approved=answer in {"y", "yes"}, note=note,
            ))
            continue
        if result.status == "awaiting_selection":
            candidates = json.loads(Path(
                result.artifacts["candidate_index"]
            ).read_text(encoding="utf-8"))
            available = [
                candidate for candidate in candidates
                if candidate.get("status") == "generated"
            ]
            print("Generated candidates:")
            for candidate in available:
                print(
                    f"  {candidate['candidate_id']}: "
                    f"{candidate['direction_seed']['label']} "
                    f"({candidate['image_path']})"
                )
            selected = input(
                "Select a candidate id, or press Enter to discard all: "
            ).strip()
            valid = {candidate["candidate_id"] for candidate in available}
            if selected and selected not in valid:
                print("Unknown or unavailable candidate id.")
                continue
            result = app.resume(result.run_id, CandidateSelection(
                selected_candidate_id=selected or None,
            ))
            continue
        return 0 if result.status in {"completed", "rejected"} else 1
