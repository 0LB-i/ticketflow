"""Configuração lida das variáveis de ambiente (docs/18 §18.3, passo 6)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://chamados:chamados@localhost:5432/chamados"
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"
    # Endereço público, usado nos links dos e-mails (convite, redefinição de senha).
    app_base_url: str = "http://localhost:8000"

    # Sessões (docs/09 §9.7). Em produção o cookie é sempre Secure.
    cookie_secure: bool = True
    session_idle_hours: int = 8
    session_max_days: int = 7

    # E-mail (questão 1). Sem SMTP_HOST, os e-mails vão para o log e a tela de usuários
    # mostra os links de convite e redefinição para o administrador repassar.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    smtp_from: str = "TicketFlow <ticketflow@localhost>"

    # Anexos (docs/11 §11.6): só o usuário do serviço acessa. Entra no backup junto com o banco.
    files_dir: Path = Path("/var/lib/ticketflow/files")


@lru_cache
def get_settings() -> Settings:
    return Settings()
