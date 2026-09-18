from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from app.services.public_url import canonical_public_origin


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_OPERATIONS_DATABASE = PROJECT_ROOT / "data" / "operations.db"


class Settings(BaseSettings):
    app_environment: str = "development"
    local_dashboard_bypass: bool = False
    tomtom_api_key: str = ""
    azure_maps_subscription_key: str = ""
    azure_maps_api_url: str = "https://atlas.microsoft.com"
    azure_maps_timeout_seconds: float = 15.0
    openrouteservice_api_key: str = ""
    openweather_api_key: str = ""
    trafegus_api_key: str = ""
    trafegus_api_url: str = "https://sevencargo.trafegus.com.br/ws_rest/public/api"
    trafegus_username: str = ""
    trafegus_password: str = ""
    trafegus_app_id: str = "777"
    trafegus_documento: str = ""
    trafegus_timeout_seconds: float = 30.0
    trafegus_retry_attempts: int = 2
    tracking_api_key: str = ""
    public_trip_internal_api_key: str = ""
    panel_admin_username: str = ""
    panel_admin_password_hash: str = ""
    creator_delete_password_hash: str = ""
    panel_admin_role: str = "Administrador"
    panel_users_file: Path | None = None
    panel_session_secret: str = ""
    panel_session_ttl_hours: int = 8
    panel_cookie_secure: bool = False
    force_https: bool = False
    expose_api_docs: bool = True
    login_rate_limit_attempts: int = 5
    login_rate_limit_window_seconds: int = 60
    sensitive_rate_limit_attempts: int = 30
    sensitive_rate_limit_window_seconds: int = 60
    public_trip_base_url: str = "http://localhost:5174"
    public_trip_token_pepper: str = ""
    public_trip_default_ttl_hours: int = 168
    public_trip_contact_name: str = "Central Seven Cargo"
    public_trip_contact_phone: str = ""
    public_trip_instructions: str = ""
    driver_mobile_location_enabled: bool = False
    driver_mobile_location_min_interval_seconds: int = 15
    driver_mobile_location_max_per_minute: int = 6
    driver_mobile_location_max_accuracy_m: float = 1000
    driver_mobile_location_stale_minutes: int = 10
    driver_mobile_location_divergence_km: float = 5
    driver_portal_alerts_enabled: bool = False
    driver_portal_pilot_trip_keys: str = ""
    driver_alert_max_age_minutes: int = 180
    driver_alert_route_corridor_km: float = 5
    driver_alert_card_near_km: float = 150
    driver_alert_card_critical_km: float = 250
    driver_alert_slow_traffic_first_km: float = 10
    driver_alert_slow_traffic_reinforce_km: float = 3
    driver_alert_blockage_first_km: float = 20
    driver_alert_blockage_reinforce_km: float = 5
    driver_alert_light_rain_first_km: float = 10
    driver_alert_light_rain_reinforce_km: float = 2
    driver_alert_heavy_rain_first_km: float = 30
    driver_alert_heavy_rain_reinforce_km: float = 10
    driver_alert_place_first_km: float = 5
    driver_alert_place_reinforce_km: float = 1
    frontend_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    allowed_hosts: str = "localhost,127.0.0.1"
    operations_database_path: Path = DEFAULT_OPERATIONS_DATABASE
    route_geometry_bootstrap_enabled: bool = True
    fleet_collector_enabled: bool = True
    fleet_collector_interval_seconds: int = 60
    fleet_collector_initial_delay_seconds: int = 5
    fleet_routing_enabled: bool = False
    fleet_position_fresh_minutes: int = 15
    return_min_destination_stay_hours: float = 18
    return_min_progress_km: float = 40
    return_direction_readings: int = 3
    return_corridor_m: float = 1000
    angellira_dataset_path: str = "data/angellira/2026-07-23-v1"
    risk_area_dwell_warning_minutes: int = 15
    risk_area_dwell_critical_minutes: int = 30
    risk_area_min_consecutive_positions: int = 3
    risk_area_max_position_age_minutes: int = 10
    risk_area_max_stop_movement_meters: float = 250
    homologated_station_geofence_meters: float = 300
    traffic_collector_enabled: bool = True
    traffic_collector_interval_seconds: int = 180
    traffic_collector_initial_delay_seconds: int = 15
    traffic_corridor_km: float = 15
    traffic_route_corridor_meters: float = 500
    traffic_route_corridor_highway_meters: float = 1000
    traffic_lookahead_km: float = 350
    traffic_query_spacing_km: float = 60
    traffic_max_incident_calls_per_cycle: int = 12
    traffic_incident_default_ttl_minutes: int = 30
    operations_backup_enabled: bool = True
    operations_backup_interval_hours: int = 24
    operations_backup_initial_delay_seconds: int = 120
    operations_backup_daily_retention: int = 7
    operations_backup_weekly_retention: int = 4
    operations_backup_monthly_retention: int = 6
    automatic_reports_directory: Path = PROJECT_ROOT / "data" / "reports" / "automatic"
    driver_evaluation_due_hours: int = 24
    weekly_writeback_enabled: bool = False
    weekly_writeback_spreadsheet_id: str = ""
    weekly_writeback_sheet_name: str = "LHW38"
    google_oauth_client_path: Path = PROJECT_ROOT / "secrets"
    google_sheets_token_path: Path = PROJECT_ROOT / "secrets" / "google_sheets_token.json"

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("public_trip_base_url")
    @classmethod
    def valid_public_trip_base_url(cls, value: str) -> str:
        return canonical_public_origin(value)

    @field_validator("operations_database_path", mode="before")
    @classmethod
    def absolute_operations_database_path(cls, value: str | Path) -> Path:
        path = Path(value)
        return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()

    @field_validator("automatic_reports_directory", mode="before")
    @classmethod
    def absolute_reports_path(cls, value: str | Path) -> Path:
        path = Path(value)
        return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()

    @field_validator("google_oauth_client_path", "google_sheets_token_path", mode="before")
    @classmethod
    def absolute_google_secret_path(cls, value: str | Path) -> Path:
        path = Path(value)
        return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()

    @field_validator("panel_users_file", mode="before")
    @classmethod
    def absolute_users_path(cls, value: str | Path | None) -> Path | None:
        if value is None or not str(value).strip():
            return None
        path = Path(value)
        return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()

    @property
    def development(self) -> bool:
        return self.app_environment.strip().lower() in {"development", "dev", "local"}

    def driver_portal_feature_allowed(self, trip_key: str, enabled: bool) -> bool:
        """Require both the feature switch and an explicit pilot trip allowlist."""
        selected = {
            value.strip()
            for value in self.driver_portal_pilot_trip_keys.split(",")
            if value.strip()
        }
        return bool(enabled and trip_key in selected)

    def validate_public_trip_runtime(self) -> None:
        if not self.public_trip_token_pepper.strip():
            raise RuntimeError(
                f"PUBLIC_TRIP_TOKEN_PEPPER must be configured in {ENV_FILE}"
            )

    def validate_security_runtime(self) -> None:
        if not self.development:
            if not self.panel_cookie_secure:
                raise RuntimeError("PANEL_COOKIE_SECURE must be true outside development")
            if not self.force_https:
                raise RuntimeError("FORCE_HTTPS must be true outside development")
            origins = [value.strip() for value in self.frontend_origins.split(",") if value.strip()]
            if not origins or "*" in origins or any(not value.startswith("https://") for value in origins):
                raise RuntimeError("FRONTEND_ORIGINS must contain only explicit HTTPS origins")
            hosts = [value.strip() for value in self.allowed_hosts.split(",") if value.strip()]
            if not hosts or "*" in hosts:
                raise RuntimeError("ALLOWED_HOSTS must contain explicit production hosts")


@lru_cache
def get_settings() -> Settings:
    return Settings()
