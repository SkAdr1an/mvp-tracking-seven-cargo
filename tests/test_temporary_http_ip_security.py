from pathlib import Path

import pytest

from app.core.config import Settings


HTTP_IP = "http://190.2.184.66"
IP = "190.2.184.66"


def production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_environment": "production",
        "frontend_origins": "https://tracking.example.com",
        "allowed_hosts": "tracking.example.com",
        "panel_cookie_secure": True,
        "force_https": True,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_exact_temporary_http_ip_mode_is_accepted() -> None:
    production_settings(
        frontend_origins=HTTP_IP,
        allowed_hosts=IP,
        panel_cookie_secure=False,
        force_https=False,
    ).validate_security_runtime()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("frontend_origins", "http://190.2.184.67"),
        ("frontend_origins", "http://localhost"),
        ("frontend_origins", "*"),
        ("frontend_origins", f"{HTTP_IP},https://tracking.example.com"),
        ("allowed_hosts", "190.2.184.67"),
        ("allowed_hosts", "localhost"),
        ("allowed_hosts", "*"),
        ("panel_cookie_secure", True),
        ("force_https", True),
    ],
)
def test_temporary_http_ip_mode_rejects_every_variation(field: str, value: object) -> None:
    values: dict[str, object] = {
        "frontend_origins": HTTP_IP,
        "allowed_hosts": IP,
        "panel_cookie_secure": False,
        "force_https": False,
        field: value,
    }
    with pytest.raises(RuntimeError):
        production_settings(**values).validate_security_runtime()


def test_normal_explicit_https_configuration_remains_accepted() -> None:
    production_settings().validate_security_runtime()


def test_deployment_routes_only_the_literal_temporary_http_ip() -> None:
    root = Path(__file__).resolve().parents[1]
    caddyfile = (root / "Caddyfile").read_text(encoding="utf-8")
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")

    assert "http://190.2.184.66 {" in caddyfile
    assert "http://localhost" not in caddyfile
    assert "PANEL_COOKIE_SECURE: ${PANEL_COOKIE_SECURE:-true}" in compose
    assert "FORCE_HTTPS: ${FORCE_HTTPS:-true}" in compose
    assert 'VITE_PUBLIC_APP_URL: ""' in compose
