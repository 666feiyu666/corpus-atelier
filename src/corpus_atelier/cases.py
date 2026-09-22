"""Discover and validate bundled experiment cases from filesystem manifests."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from .artifacts.store import validate_case_id
from .design.validation import validate
from .registry import get_profile


CASE_MANIFEST_KEYS = {
    "format_version",
    "label",
    "profile",
    "order",
    "default_reference_id",
    "default_reference_mode",
}
REFERENCE_MODES = {"style_grounded", "style_inspired"}


@dataclass(frozen=True)
class ExampleCase:
    case_id: str
    label: str
    profile: str
    brief_path: Path
    order: int = 100
    default_reference_id: str | None = None
    default_reference_mode: str | None = None


def _read_object(path: Path, description: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Missing {description}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {description} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{description.capitalize()} must be a JSON object: {path}")
    return value


def _optional_nonempty_string(manifest: dict, key: str, path: Path) -> str | None:
    value = manifest.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{key} must be a non-empty trimmed string in {path}.")
    return value


def _load_case(directory: Path) -> ExampleCase:
    case_id = validate_case_id(directory.name)
    manifest_path = directory / "case.json"
    brief_path = directory / "brief.json"
    manifest = _read_object(manifest_path, "case manifest")
    unknown = set(manifest) - CASE_MANIFEST_KEYS
    if unknown:
        raise ValueError(
            f"Unknown case manifest fields in {manifest_path}: {', '.join(sorted(unknown))}."
        )
    if manifest.get("format_version") != 1:
        raise ValueError(f"Unsupported case manifest format_version in {manifest_path}.")

    label = _optional_nonempty_string(manifest, "label", manifest_path)
    profile_name = _optional_nonempty_string(manifest, "profile", manifest_path)
    if label is None or profile_name is None:
        raise ValueError(f"Case manifest requires label and profile: {manifest_path}")
    profile = get_profile(profile_name)

    order = manifest.get("order", 100)
    if isinstance(order, bool) or not isinstance(order, int):
        raise ValueError(f"order must be an integer in {manifest_path}.")

    reference_id = _optional_nonempty_string(
        manifest, "default_reference_id", manifest_path,
    )
    reference_mode = _optional_nonempty_string(
        manifest, "default_reference_mode", manifest_path,
    )
    if (reference_id is None) != (reference_mode is None):
        raise ValueError(
            "default_reference_id and default_reference_mode must be provided together "
            f"in {manifest_path}."
        )
    if reference_mode is not None and reference_mode not in REFERENCE_MODES:
        raise ValueError(
            f"Unsupported default_reference_mode {reference_mode!r} in {manifest_path}."
        )

    brief = _read_object(brief_path, "case brief")
    validate(brief, profile.brief_schema)
    return ExampleCase(
        case_id=case_id,
        label=label,
        profile=profile_name,
        brief_path=brief_path.resolve(),
        order=order,
        default_reference_id=reference_id,
        default_reference_mode=reference_mode,
    )


def discover_cases(root: Path | str) -> dict[str, ExampleCase]:
    """Return validated cases ordered for display and keyed by unique label."""
    cases_root = Path(root).resolve()
    if not cases_root.is_dir():
        raise ValueError(f"Cases directory does not exist: {cases_root}")

    cases: list[ExampleCase] = []
    for directory in sorted(cases_root.iterdir(), key=lambda path: path.name):
        if not directory.is_dir():
            continue
        manifest_path = directory / "case.json"
        brief_path = directory / "brief.json"
        if not manifest_path.exists():
            if brief_path.exists():
                raise ValueError(
                    f"Case {directory.name!r} has brief.json but no case.json manifest."
                )
            continue
        cases.append(_load_case(directory))

    if not cases:
        raise ValueError(f"No registered cases found in {cases_root}.")
    cases.sort(key=lambda case: (case.order, case.label, case.case_id))

    catalog: dict[str, ExampleCase] = {}
    case_ids: set[str] = set()
    for case in cases:
        if case.label in catalog:
            raise ValueError(f"Duplicate case label: {case.label!r}.")
        if case.case_id in case_ids:
            raise ValueError(f"Duplicate case id: {case.case_id!r}.")
        catalog[case.label] = case
        case_ids.add(case.case_id)
    return catalog
