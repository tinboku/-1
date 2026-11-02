"""Runtime configuration, all from environment variables.

Nothing here is secret by itself; API keys are read from the environment
only and never written to disk by this package.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value.strip()
    return None


@dataclass
class Config:
    # Data sources
    s2_api_key: str | None = None          # SEMANTIC_SCHOLAR_API_KEY / S2_API_KEY
    openalex_api_key: str | None = None    # OPENALEX_API_KEY
    contact_email: str | None = None       # CROSSREF_EMAIL / OPENALEX_EMAIL (polite pools)

    # LLM backend (OpenAI-compatible). Without a key the heuristic backend is used.
    llm_api_key: str | None = None         # LLM_API_KEY / OPENAI_API_KEY
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"

    # Storage
    data_dir: Path = Path.home() / ".dls"

    @classmethod
    def from_env(cls) -> "Config":
        data_dir = os.environ.get("DLS_HOME")
        return cls(
            s2_api_key=_first_env("SEMANTIC_SCHOLAR_API_KEY", "S2_API_KEY"),
            openalex_api_key=_first_env("OPENALEX_API_KEY"),
            contact_email=_first_env("CROSSREF_EMAIL", "OPENALEX_EMAIL"),
            llm_api_key=_first_env("LLM_API_KEY", "OPENAI_API_KEY"),
            llm_base_url=os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1"),
            llm_model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
            data_dir=Path(data_dir) if data_dir else Path.home() / ".dls",
        )

    @property
    def db_path(self) -> Path:
        return self.data_dir / "library.db"

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.files_dir.mkdir(parents=True, exist_ok=True)
