#!/usr/bin/env python3
"""Lint changed plugins and shared Markdown between two Git revisions.

Shared lint configuration or tool changes require a full repository check.
Run from the repository root with --base BASE --head HEAD.
"""

import argparse
import subprocess
from pathlib import PurePosixPath


def git_paths(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args], check=True, stdout=subprocess.PIPE,
    )
    return result.stdout.decode("utf-8").rstrip("\0").split("\0") if result.stdout else []


def select_paths(changed: list[str], tracked: list[str]) -> list[str]:
    plugins = {
        PurePosixPath(path).parts[1]
        for path in changed
        if len(PurePosixPath(path).parts) >= 3
        and PurePosixPath(path).parts[0] == "plugins"
    }
    changed_paths = set(changed)
    selected = []
    for path in tracked:
        parts = PurePosixPath(path).parts
        if not path.endswith(".md") or "node_modules" in parts:
            continue
        if len(parts) >= 3 and parts[0] == "plugins":
            if parts[1] in plugins:
                selected.append(path)
        elif path in changed_paths:
            selected.append(path)
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    args = parser.parse_args()

    # Disable rename detection so both the old and new plugin are checked.
    changed = git_paths(
        "diff", "--name-only", "-z", "--no-renames", args.base, args.head, "--",
    )
    if {".markdownlint-cli2.yaml", "mise.toml"}.intersection(changed):
        print("Shared lint inputs changed; linting all Markdown.", flush=True)
        patterns = ["**/*.md", "#node_modules"]
    else:
        paths = select_paths(changed, git_paths("ls-files", "-z", "--", "*.md"))
        if not paths:
            print("No Markdown files in the changed scopes.")
            return 0
        print(f"Linting {len(paths)} Markdown files in the changed scopes.", flush=True)
        # The CLI's literal-path prefix preserves spaces and glob metacharacters.
        patterns = [f":{path}" for path in paths]
    return subprocess.run(["markdownlint-cli2", "--no-globs", *patterns]).returncode


if __name__ == "__main__":
    raise SystemExit(main())
