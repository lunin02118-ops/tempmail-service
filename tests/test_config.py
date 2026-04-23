from pathlib import Path

import app.config as config_module
from app.config import AppSettings, GENERATED_MAIL_DOMAIN_PREFIXES


def test_settings_build_paths_and_poll_seconds_from_env(tmp_path, monkeypatch):
    secret_path = tmp_path / "client_secret.json"
    token_path = tmp_path / "token.json"

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET_PATH", str(secret_path))
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(token_path))
    monkeypatch.setenv("GMAIL_POLL_SECONDS", "45")
    monkeypatch.setenv("DEFAULT_FROM_ALIAS_DOMAIN", "example.com")

    settings = AppSettings.from_env()

    assert settings.app_env == "dev"
    assert settings.database_url.endswith("app.db")
    assert settings.gmail_client_secret_path == secret_path
    assert settings.gmail_token_path == token_path
    assert settings.gmail_poll_seconds == 45
    assert settings.default_from_alias_domain == "example.com"


def test_settings_default_poll_interval(tmp_path, monkeypatch):
    monkeypatch.delenv("GMAIL_POLL_SECONDS", raising=False)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET_PATH", str(tmp_path / 'client_secret.json'))
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(tmp_path / 'token.json'))

    settings = AppSettings.from_env()

    assert settings.gmail_poll_seconds == 60


def test_settings_collects_groq_keys_from_numbered_env_vars(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.delenv("GROQ_API_KEYS", raising=False)
    for index in range(1, 10):
        monkeypatch.delenv(f"GROQ_API_KEY_{index}", raising=False)
    monkeypatch.setenv("GROQ_API_KEY_1", "groq-key-1")
    monkeypatch.setenv("GROQ_API_KEY_2", "groq-key-2")

    settings = AppSettings.from_env()

    assert settings.groq_api_keys == ("groq-key-1", "groq-key-2")


def test_settings_expand_public_mail_domains_with_generated_variants(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("PUBLIC_MAIL_DOMAIN", "samgpt.me")
    monkeypatch.delenv("PUBLIC_MAIL_DOMAINS", raising=False)

    settings = AppSettings.from_env()

    assert settings.public_mail_domains[0] == "samgpt.me"
    assert len(settings.public_mail_domains) == len(GENERATED_MAIL_DOMAIN_PREFIXES) + 1
    assert "atlas.samgpt.me" in settings.public_mail_domains
    assert "zen.samgpt.me" in settings.public_mail_domains


def test_settings_load_private_values_from_env_local(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PUBLIC_MAIL_DOMAIN", raising=False)
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path)

    (tmp_path / ".env.local").write_text(
        "\n".join(
            (
                "APP_ENV=dev",
                "DATABASE_URL=sqlite:///./data/app.db",
                "PUBLIC_MAIL_DOMAIN=samgpt.me",
                "SESSION_SECRET=local-secret",
            )
        ),
        encoding="utf-8",
    )

    settings = AppSettings.from_env()

    assert settings.app_env == "dev"
    assert settings.public_mail_domain == "samgpt.me"
    assert settings.session_secret == "local-secret"
    assert settings.database_url.endswith(str(Path("data/app.db")))
