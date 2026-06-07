from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GitStatus:
    is_repo: bool
    branch: str | None = None
    head: str | None = None
    changed_files: tuple[str, ...] = ()
    unpushed_commits: int | None = None
    recent_commits: tuple[str, ...] = ()
    error: str | None = None


def inspect_git(project: Path) -> GitStatus:
    if not (project / ".git").exists() and not run_git(project, "rev-parse", "--is-inside-work-tree").ok:
        return GitStatus(is_repo=False)

    branch = run_git(project, "branch", "--show-current").stdout.strip() or None
    head = run_git(project, "rev-parse", "--short", "HEAD").stdout.strip() or None
    changed = tuple(line for line in run_git(project, "status", "--short").stdout.splitlines() if line.strip())
    commits = tuple(line for line in run_git(project, "log", "--oneline", "-5").stdout.splitlines() if line.strip())
    upstream = run_git(project, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    unpushed = None
    if upstream.ok:
        count = run_git(project, "rev-list", "--count", "@{u}..HEAD")
        if count.ok and count.stdout.strip().isdigit():
            unpushed = int(count.stdout.strip())
    return GitStatus(True, branch, head, changed, unpushed, commits)


@dataclass(frozen=True)
class CmdResult:
    ok: bool
    stdout: str
    stderr: str


def run_git(project: Path, *args: str) -> CmdResult:
    try:
        proc = subprocess.run(
            ["git", "-C", str(project), *args],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        return CmdResult(False, "", str(exc))
    return CmdResult(proc.returncode == 0, proc.stdout, proc.stderr)
