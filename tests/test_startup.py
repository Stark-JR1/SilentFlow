from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.core.templates import build_templates


def test_app_imports_without_traceback():
    import main

    assert main.app.title == "FinTrack Pro"


def test_required_directories_exist():
    assert Path("app").is_dir()
    assert Path("templates").is_dir()
    assert Path("static").is_dir()


def test_templates_are_configured_with_custom_filters():
    templates = build_templates()

    assert "currency" in templates.env.filters
    assert "date_br" in templates.env.filters
    assert templates.get_template("base.html") is not None


def test_settings_load_required_environment():
    get_settings.cache_clear()
    settings = get_settings()

    assert str(settings.supabase_url).startswith("http")
    assert settings.supabase_anon_key
    assert settings.supabase_service_role_key


def test_settings_fail_clearly_without_env_and_dotenv(monkeypatch):
    import app.core.config as config_module

    get_settings.cache_clear()
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.setattr(config_module.os.path, "exists", lambda _path: False)

    with pytest.raises(RuntimeError, match="Arquivo .env nao encontrado"):
        config_module.get_settings()

    get_settings.cache_clear()


def test_settings_reject_malformed_supabase_url():
    monkeypatch = pytest.MonkeyPatch()
    get_settings.cache_clear()
    monkeypatch.setenv("SUPABASE_URL", "not-a-url")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service")

    with pytest.raises(ValidationError):
        Settings()

    monkeypatch.undo()
