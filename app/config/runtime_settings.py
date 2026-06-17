from dataclasses import asdict, dataclass
from functools import lru_cache
import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_ENV_PATH = ROOT_DIR / ".env"


def load_environment(env_path: Path | None = None) -> None:
    path = env_path or DEFAULT_ENV_PATH
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if value and len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class JiraRuntimeSettings:
    base_url: str = ""
    email: str = ""
    api_token: str = ""
    project_key: str = ""
    issue_type: str = "Task"

    @property
    def configured(self) -> bool:
        return all([self.base_url, self.email, self.api_token, self.project_key, self.issue_type])

    def public_payload(self) -> dict:
        payload = asdict(self)
        payload["configured"] = self.configured
        payload["api_token"] = "***configured***" if self.api_token else ""
        payload["email"] = "***configured***" if self.email else ""
        return payload


@dataclass(frozen=True)
class EmbeddingRuntimeSettings:
    """Configuración del modelo de embeddings local para el RAG (Decisión 012)."""
    base_url: str = "http://127.0.0.1:11434/api"
    model: str = "embeddinggemma:latest"
    enabled: bool = True


@dataclass(frozen=True)
class GitRuntimeSettings:
    repo_path: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.repo_path) and Path(self.repo_path).is_dir()


@dataclass(frozen=True)
class GitHubRuntimeSettings:
    """Configuración del cliente GitHub para detectar PRs / merges asociados
    a un compromiso (Decisión 023). Requiere un Personal Access Token con
    el scope ``repo`` (lectura) y la coordenada ``owner/repo`` del
    repositorio donde el equipo trabaja sobre los compromisos.

    El cliente nunca escribe en GitHub. Solo consulta commits y PRs vía la
    API REST oficial v3 para detectar evidencia técnica."""
    token: str = ""
    repo: str = ""           # owner/repo
    base_url: str = "https://api.github.com"
    user_agent: str = "meeting-traceability-bot"

    @property
    def configured(self) -> bool:
        return bool(self.token) and "/" in self.repo

    def public_payload(self) -> dict:
        return {
            "configured": self.configured,
            "repo": self.repo,
            "token": "***configured***" if self.token else "",
            "base_url": self.base_url,
        }


@lru_cache
def get_jira_settings() -> JiraRuntimeSettings:
    load_environment()
    return JiraRuntimeSettings(
        base_url=os.getenv("JIRA_BASE_URL", "").strip(),
        email=os.getenv("JIRA_EMAIL", "").strip(),
        api_token=os.getenv("JIRA_API_TOKEN", "").strip(),
        project_key=os.getenv("JIRA_PROJECT_KEY", "").strip(),
        issue_type=os.getenv("JIRA_ISSUE_TYPE", "Task").strip() or "Task",
    )


@lru_cache
def get_git_settings() -> GitRuntimeSettings:
    load_environment()
    return GitRuntimeSettings(repo_path=os.getenv("GIT_REPO_PATH", "").strip())


@lru_cache
def get_github_settings() -> GitHubRuntimeSettings:
    load_environment()
    return GitHubRuntimeSettings(
        token=os.getenv("GITHUB_TOKEN", "").strip(),
        repo=os.getenv("GITHUB_REPO", "").strip(),
        base_url=os.getenv("GITHUB_BASE_URL", "https://api.github.com").strip()
        or "https://api.github.com",
    )


@lru_cache
def get_embedding_settings() -> EmbeddingRuntimeSettings:
    """Configuración del modelo de embeddings (Decisión 012). Por defecto activa.

    Se desactiva poniendo `EMBEDDING_ENABLED=0` en `.env`, en cuyo caso el pipeline corre sin
    recuperación (comportamiento previo a Decisión 012).
    """
    load_environment()
    enabled = os.getenv("EMBEDDING_ENABLED", "1").strip() not in {"0", "false", "False", ""}
    return EmbeddingRuntimeSettings(
        base_url=os.getenv("EMBEDDING_BASE_URL", "http://127.0.0.1:11434/api").strip()
        or "http://127.0.0.1:11434/api",
        model=os.getenv("EMBEDDING_MODEL", "embeddinggemma:latest").strip() or "embeddinggemma:latest",
        enabled=enabled,
    )


load_environment()
