"""Resolve task-owned files before reading requests or reference images."""

from pathlib import Path

from .hashing import digest_file


def task_path(root: Path, relative: str | Path) -> Path:
    path = (root / relative).resolve(strict=True)
    if root not in path.parents:
        raise ValueError("The artifact is outside its task directory.")
    return path


def verified_image(root: Path, relative: str | Path, sha256: str) -> Path:
    path = task_path(root, relative)
    if digest_file(path) != sha256:
        raise ValueError("A reference or feedback image has changed.")
    return path
