import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.config.runtime_settings import GitRuntimeSettings, get_git_settings


class GitClientError(Exception):
    pass


@dataclass(frozen=True)
class GitCommit:
    hash: str
    message: str
    author: str
    date: str


class GitRepositoryClient:
    def __init__(self, settings: GitRuntimeSettings | None = None) -> None:
        self.settings = settings or get_git_settings()

    def is_configured(self) -> bool:
        return self.settings.configured

    def search_commits(self, keywords: list[str], limit: int = 10) -> list[GitCommit]:
        if not self.is_configured():
            return []
        if not keywords:
            return []

        results: list[GitCommit] = []
        seen: set[str] = set()

        for keyword in keywords[:4]:
            if not keyword.strip():
                continue
            commits = self._grep_commits(keyword.strip(), limit=limit)
            for commit in commits:
                if commit.hash not in seen:
                    results.append(commit)
                    seen.add(commit.hash)

        return results[:limit]

    def _grep_commits(self, pattern: str, limit: int) -> list[GitCommit]:
        limit = max(1, limit)
        try:
            result = subprocess.run(
                [
                    "git", "log",
                    f"--grep={pattern}",
                    "-i",
                    f"-{limit}",
                    "--format=%H%x1f%s%x1f%an%x1f%ad",
                    "--date=short",
                ],
                cwd=self.settings.repo_path,
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                return []

            commits = []
            for line in result.stdout.strip().splitlines():
                parts = line.split("\x1f")
                if len(parts) == 4:
                    commits.append(GitCommit(hash=parts[0][:12], message=parts[1], author=parts[2], date=parts[3]))
            return commits
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []
