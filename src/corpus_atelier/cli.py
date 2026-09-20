"""Command-line UI for the Corpus Atelier application."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from .application import CorpusAtelierApplication
from .artifacts.records import write_json, write_text
from .design.prompt_compiler import compile_reference_plan_prompt
from .design.validation import validate
from .rag import build_reference_package, retrieve
from .registry import PROFILES, get_profile
from .state import DesignJob, HumanDecision, RevisionDecision


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="corpus-atelier")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("profiles", help="List registered design profiles.")
    validate_cmd = commands.add_parser("validate", help="Validate a brief without model calls.")
    validate_cmd.add_argument("--profile", required=True, choices=PROFILES)
    validate_cmd.add_argument("--brief", required=True, type=Path)
    run = commands.add_parser("run", help="Run one review-gated design experiment.")
    run.add_argument("--profile", required=True, choices=PROFILES)
    run.add_argument("--brief", required=True, type=Path)
    run.add_argument(
        "--snapshot", type=Path,
        default=Path("experiments/atlas-snapshot/mucha-commercial"),
    )
    run.add_argument("--evidence-mode", choices=["hybrid-rag", "knowledge-only", "no-rag"],
                     default="hybrid-rag")
    preview = commands.add_parser(
        "preview-reference", help="Compile reference inputs without provider calls.",
    )
    preview.add_argument("--profile", required=True, choices=PROFILES)
    preview.add_argument("--brief", required=True, type=Path)
    preview.add_argument(
        "--snapshot", type=Path,
        default=Path("experiments/atlas-snapshot/mucha-commercial"),
    )
    preview.add_argument("--evidence-mode", choices=["hybrid-rag", "knowledge-only"],
                         default="hybrid-rag")
    preview.add_argument("--output", required=True, type=Path)
    inspect = commands.add_parser("inspect", help="Inspect a saved experiment.")
    inspect.add_argument("run_id")
    inspect.add_argument("--runs-root", type=Path, default=Path("experiments/runs"))
    return parser


def _read_brief(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Brief must be a JSON object.")
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
        validate(_read_brief(args.brief), profile.brief_schema)
        print(f"Valid {profile.name} brief: {args.brief.resolve()}")
        return 0
    if args.command == "preview-reference":
        profile = get_profile(args.profile)
        brief = _read_brief(args.brief)
        validate(brief, profile.brief_schema)
        mode = brief.get("reference_mode")
        scope = brief.get("reference_scope")
        if not mode or not scope:
            raise ValueError("Reference preview requires reference_mode and reference_scope.")
        _, _, bundle = retrieve(
            brief, profile.name, args.snapshot, evidence_mode=args.evidence_mode,
        )
        package, _ = build_reference_package(args.snapshot, scope=scope)
        prompt = compile_reference_plan_prompt(
            mode=mode, brief=brief, bundle=bundle, package=package,
        )
        output = args.output.resolve()
        write_json(output / "retrieval-bundle.json", bundle)
        write_json(output / "reference-package.json", package)
        write_text(output / "reference-plan-prompt.md", prompt)
        print(f"Reference preview: {output}")
        return 0
    app = CorpusAtelierApplication(runs_root=getattr(args, "runs_root", "experiments/runs"))
    if args.command == "inspect":
        summary = app.inspect(args.run_id)
        print(json.dumps(summary.manifest, ensure_ascii=False, indent=2))
        return 0
    load_dotenv()
    result = app.start(DesignJob(
        profile=args.profile, brief=_read_brief(args.brief), snapshot=args.snapshot,
        evidence_mode=args.evidence_mode,
    ))
    while True:
        _print_result(result)
        if result.status == "awaiting_approval":
            answer = input("Approve this exact image-generation request? [y/N] ").strip().lower()
            note = input("Approval note (optional): ").strip() if answer in {"y", "yes"} else ""
            result = app.resume(result.run_id, HumanDecision(
                approved=answer in {"y", "yes"}, note=note,
            ))
            continue
        if result.status == "awaiting_revision":
            action = input("Accept, revise, or discard this image? [a/r/d] ").strip().lower()
            if action in {"a", "accept"}:
                decision = RevisionDecision("accept")
            elif action in {"r", "revise"}:
                instruction = input("State the exact revision request: ").strip()
                decision = RevisionDecision("revise", instruction=instruction)
            elif action in {"d", "discard"}:
                decision = RevisionDecision("discard")
            else:
                print("Please enter a, r, or d.")
                continue
            result = app.resume(result.run_id, decision)
            continue
        if result.status == "awaiting_revision_approval":
            answer = input("Approve this exact image-edit request? [y/N] ").strip().lower()
            note = input("Approval note (optional): ").strip() if answer in {"y", "yes"} else ""
            result = app.resume(result.run_id, HumanDecision(
                approved=answer in {"y", "yes"}, note=note,
            ))
            continue
        return 0 if result.status in {"completed", "rejected", "discarded"} else 1
