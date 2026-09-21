"""Command-line adapter for reproducible Corpus Atelier experiments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from .application import CorpusAtelierApplication
from .artifacts.records import write_json, write_text
from .design.prompt_compiler import compile_reference_plan_prompt
from .design.validation import validate
from .materials import build_material_package
from .registry import PROFILES, get_profile
from .state import DesignJob, FinalDecision, HumanDecision


DEFAULT_SNAPSHOT = Path("experiments/atlas-snapshot/mucha-commercial")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="corpus-atelier")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("profiles", help="List registered design profiles.")

    validate_cmd = commands.add_parser("validate", help="Validate inputs without model calls.")
    validate_cmd.add_argument("--profile", required=True, choices=PROFILES)
    validate_cmd.add_argument("--brief", required=True, type=Path)
    validate_cmd.add_argument("--materials", type=Path)

    run = commands.add_parser("run", help="Run one review-gated design experiment.")
    run.add_argument("--profile", required=True, choices=PROFILES)
    run.add_argument("--brief", required=True, type=Path)
    run.add_argument("--materials", required=True, type=Path)
    run.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)

    preview = commands.add_parser(
        "preview-materials", help="Resolve selected materials without provider calls.",
    )
    preview.add_argument("--brief", required=True, type=Path)
    preview.add_argument("--materials", required=True, type=Path)
    preview.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    preview.add_argument("--output", required=True, type=Path)

    inspect = commands.add_parser("inspect", help="Inspect a saved experiment.")
    inspect.add_argument("run_id")
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
        if args.materials:
            validate(
                _read_object(args.materials, "Material selection"),
                "material-selection.schema.json",
            )
        print(f"Valid {profile.name} brief: {args.brief.resolve()}")
        return 0

    if args.command == "preview-materials":
        brief = _read_object(args.brief, "Brief")
        selection = _read_object(args.materials, "Material selection")
        package, _ = build_material_package(args.snapshot, selection)
        output = args.output.resolve()
        write_json(output / "material-selection.json", selection)
        write_json(output / "material-package.json", package)
        mode = brief.get("reference_mode")
        if mode:
            prompt = compile_reference_plan_prompt(
                mode=mode, brief=brief, materials=package,
            )
            write_text(output / "reference-plan-prompt.md", prompt)
        print(f"Material preview: {output}")
        return 0

    app = CorpusAtelierApplication(
        runs_root=getattr(args, "runs_root", "experiments/runs"),
    )
    if args.command == "inspect":
        summary = app.inspect(args.run_id)
        print(json.dumps(summary.manifest, ensure_ascii=False, indent=2))
        return 0

    load_dotenv()
    result = app.start(DesignJob(
        profile=args.profile,
        brief=_read_object(args.brief, "Brief"),
        snapshot=args.snapshot,
        materials=_read_object(args.materials, "Material selection"),
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
        if result.status == "awaiting_final_decision":
            action = input("Accept or discard this image? [a/d] ").strip().lower()
            if action in {"a", "accept"}:
                decision = FinalDecision("accept")
            elif action in {"d", "discard"}:
                decision = FinalDecision("discard")
            else:
                print("Please enter a or d.")
                continue
            result = app.resume(result.run_id, decision)
            continue
        return 0 if result.status in {"completed", "rejected", "discarded"} else 1
