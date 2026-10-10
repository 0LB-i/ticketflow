"""Configuração lida das variáveis de ambiente (docs/18 §18.3, passo 6)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://chamados:chamados@localhost:5432/chamados"
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"
    # SPA compilada servida na mesma origem da API (ADR 0010). Em dev, o Vite faz o proxy.
    frontend_dist: Path = REPO_ROOT / "frontend" / "dist"


@lru_cache
def get_settings() -> Settings:
    return Settings()
