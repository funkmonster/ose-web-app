"""
Configuration for the OSE App backend.
Loads LLM/env settings and the users.yaml identity file.
"""

import os
import yaml
from pathlib import Path


class Config:
    # ─── Paths ───────────────────────────────────────────────────────────────
    BASE_DIR = Path(__file__).resolve().parent.parent
    DB_PATH: str = os.getenv("DB_PATH", str(BASE_DIR / "data" / "campaign.db"))
    USERS_FILE: str = os.getenv("USERS_FILE", str(BASE_DIR / "users.yaml"))
    STATIC_DIR: str = os.getenv("STATIC_DIR", str(BASE_DIR / "static"))

    # ─── LLM Provider ────────────────────────────────────────────────────────
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "anthropic")

    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")

    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3")

    # ─── Context Management ──────────────────────────────────────────────────
    HISTORY_WINDOW: int = int(os.getenv("HISTORY_WINDOW", "20"))
    SUMMARIZE_EVERY: int = int(os.getenv("SUMMARIZE_EVERY", "10"))
    SUMMARIZE_CONTEXT_WINDOW: int = int(os.getenv("SUMMARIZE_CONTEXT_WINDOW", "40"))

    # ─── Users ───────────────────────────────────────────────────────────────
    _users_cache = None

    @classmethod
    def load_users(cls) -> list[dict]:
        """Load and cache the users.yaml file."""
        if cls._users_cache is None:
            with open(cls.USERS_FILE) as f:
                data = yaml.safe_load(f)
            cls._users_cache = data.get("users", [])
        return cls._users_cache

    @classmethod
    def authenticate(cls, passphrase: str) -> dict | None:
        """Return the user dict matching a passphrase, or None."""
        for user in cls.load_users():
            if user.get("passphrase") == passphrase:
                return {k: v for k, v in user.items() if k != "passphrase"}
        return None

    @classmethod
    def get_user(cls, name: str) -> dict | None:
        for user in cls.load_users():
            if user.get("name") == name:
                return {k: v for k, v in user.items() if k != "passphrase"}
        return None
