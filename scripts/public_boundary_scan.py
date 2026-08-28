#!/usr/bin/env python3
"""Public-boundary scanner for the Kitty Hawk repository.

Scans the complete tracked-relevant text tree for a small set of internal
workstation/repository coordinates that must never appear in this public
repository. Runs identically from a local shell or from GitHub Actions.
Python stdlib only.

No path in this repository is exempt from the scan -- including this file.
The forbidden substrings are assembled from separated fragments (joined at
run time, never written contiguously) specifically so this scanner's own
source text does not contain the strings it looks for. This is deliberate:
detection stays uniform and full-strength everywhere rather than being
weakened by a self-match exemption.

The public GitHub URL for this repository (github.com/digitalscorpyun/kitty-hawk)
and the public author handle (digitalscorpyun) on their own are not forbidden --
only the specific private-coordinate classes below are.
"""
from __future__ import annotations

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

INCLUDE_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".json", ".txt"}

SKIP_DIR_NAMES = {
    ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".venv", "venv", "env", "_debug",
}

# Each forbidden string is built from fragments joined at run time so this
# file's own source never contains the complete substring it is checking for.
FORBIDDEN: dict[str, str] = {
    "".join(("C:", "\\", "Users", "\\")): "Windows user workstation path",
    "".join(("/mnt/c/", "Users/")): "WSL-mounted Windows user workstation path",
    "".join(("/home/", "devcontainers/")): "internal devcontainer workstation path",
    "".join(("sankofa", "_temple")): "private Vault repository name",
    "".join(("projects", "_2026")): "private Forge repository/workstation coordinate",
    "".join(("avm", "/muse/")): "internal Forge agent surface path",
    "".join(("github.com/digitalscorpyun/", "projects", "_2026")): "private Forge GitHub repository URL",
}

# Not a workstation-coordinate leak, but a distinct public-accuracy check:
# the README must not point evaluators at a private, non-shipped launcher.
FORBIDDEN_REFERENCES = {
    "".join(("_run_bounded_live_", "003")): "README references a private, non-public launcher script",
}


def iter_scannable_files(root: pathlib.Path):
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if any(part in SKIP_DIR_NAMES for part in path.relative_to(root).parts[:-1]):
            continue
        if path.suffix.lower() not in INCLUDE_SUFFIXES:
            continue
        yield path


def scan(root: pathlib.Path) -> list[str]:
    hits: list[str] = []
    for path in iter_scannable_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = path.relative_to(root)
        for needle, label in FORBIDDEN.items():
            if needle in text:
                hits.append(f"{rel}: {label}")
        if rel == pathlib.Path("README.md"):
            for needle, label in FORBIDDEN_REFERENCES.items():
                if needle in text:
                    hits.append(f"{rel}: {label}")
    return hits


def main() -> int:
    hits = scan(REPO_ROOT)
    if hits:
        print("PUBLIC-BOUNDARY SCAN: FAIL")
        for hit in hits:
            print(f"  {hit}")
        return 1
    print("PUBLIC-BOUNDARY SCAN: PASS -- 0 hits across the full tracked-relevant tree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
