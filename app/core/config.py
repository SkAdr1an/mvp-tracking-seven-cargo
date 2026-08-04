from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_OPERATIONS_DATABASE = PROJECT_ROOT / "data" / "operations.db"


class Settings(BaseSettings):
    app_environment: str = "development"
    tomtom_api_key: str = ""
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
    panel_admin_password: str = ""
    panel_session_secret: str = ""
    panel_session_ttl_hours: int = 8
    panel_cookie_secure: bool = False
    public_trip_base_url: str = "http://localhost:5173/viagem"
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
    frontend_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    operations_database_path: Path = DEFAULT_OPERATIONS_DATABASE
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

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

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

    @property
    def development(self) -> bool:
        return self.app_environment.strip().lower() in {"development", "dev", "local"}

    def validate_public_trip_runtime(self) -> None:
        if not self.public_trip_token_pepper.strip():
            raise RuntimeError(
                f"PUBLIC_TRIP_TOKEN_PEPPER must be configured in {ENV_FILE}"
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
