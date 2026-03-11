import tomllib
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_FILE_PATH = BASE_DIR / "thermocalc.config.toml"
SAMPLE_DATA_PATH = BASE_DIR / "data" / "sample_data.json"
ADMIN_STATE_PATH = BASE_DIR / "data" / "admin_state.json"
ARCHIVE_INDEX_PATH = BASE_DIR / "data" / "archive_index.json"


def _load_root_config() -> dict:
	if not CONFIG_FILE_PATH.exists():
		return {}
	return tomllib.loads(CONFIG_FILE_PATH.read_text(encoding="utf-8"))


def _read(config: dict, *keys: str, default=None):
	current = config
	for key in keys:
		if not isinstance(current, dict) or key not in current:
			return default
		current = current[key]
	return current


ROOT_CONFIG = _load_root_config()

RUNTIME_MEASUREMENTS_PATH = BASE_DIR / "data" / _read(ROOT_CONFIG, "app", "runtime_measurements_path", default="runtime_measurements.json")
GENERATED_REPORTS_DIR = BASE_DIR / _read(ROOT_CONFIG, "app", "generated_reports_dir", default="generated_reports")
SCHEDULER_POLL_SECONDS = int(_read(ROOT_CONFIG, "app", "scheduler_poll_seconds", default=60))
REALTIME_MQTT_ENABLED = bool(_read(ROOT_CONFIG, "app", "realtime_mqtt_enabled", default=True))
REALTIME_SAMPLE_FALLBACK_ENABLED = bool(_read(ROOT_CONFIG, "app", "sample_fallback_enabled", default=True))
REALTIME_MEASUREMENT_MAX_AGE_MINUTES = int(_read(ROOT_CONFIG, "app", "realtime_measurement_max_age_minutes", default=180))
TRV26_DUTY_CYCLE_WINDOW_HOURS = int(_read(ROOT_CONFIG, "app", "trv26_duty_cycle_window_hours", default=24))
TRV26_HISTORY_RETENTION_HOURS = int(_read(ROOT_CONFIG, "app", "trv26_history_retention_hours", default=72))
ZIGBEE_DISCOVERY_TIMEOUT_SECONDS = int(_read(ROOT_CONFIG, "zigbee2mqtt", "defaults", "discovery_timeout_seconds", default=8))
ZIGBEE_CONNECTIVITY_TIMEOUT_SECONDS = int(_read(ROOT_CONFIG, "zigbee2mqtt", "defaults", "connectivity_timeout_seconds", default=5))
DEFAULT_ZIGBEE2MQTT_BASE_TOPIC = str(_read(ROOT_CONFIG, "zigbee2mqtt", "defaults", "base_topic", default="zigbee2mqtt"))
DEFAULT_ZIGBEE2MQTT_URL = str(_read(ROOT_CONFIG, "zigbee2mqtt", "defaults", "mqtt_url", default="mqtt://localhost:1883"))
DEFAULT_ZIGBEE2MQTT_USERNAME = str(_read(ROOT_CONFIG, "zigbee2mqtt", "defaults", "mqtt_username", default=""))
DEFAULT_ZIGBEE2MQTT_PASSWORD = str(_read(ROOT_CONFIG, "zigbee2mqtt", "defaults", "mqtt_password", default=""))
DEFAULT_ZIGBEE2MQTT_CONTROLLER_ID = str(_read(ROOT_CONFIG, "zigbee2mqtt", "defaults", "controller_id", default="z2m-main"))
DEFAULT_ZIGBEE2MQTT_CONTROLLER_LABEL = str(_read(ROOT_CONFIG, "zigbee2mqtt", "defaults", "controller_label", default="Zigbee2MQTT Principal"))
DEFAULT_AUTO_DISCOVERY_ENABLED = bool(_read(ROOT_CONFIG, "zigbee2mqtt", "defaults", "auto_discovery_enabled", default=True))
DEFAULT_DISCOVERY_INTERVAL_MINUTES = int(_read(ROOT_CONFIG, "zigbee2mqtt", "defaults", "discovery_interval_minutes", default=15))
DEFAULT_PERMIT_JOIN_SECONDS = int(_read(ROOT_CONFIG, "zigbee2mqtt", "defaults", "permit_join_seconds", default=60))
ADMIN_USERNAME = str(_read(ROOT_CONFIG, "admin", "username", default="admin"))
ADMIN_PASSWORD = str(_read(ROOT_CONFIG, "admin", "password", default="thermocalc-admin"))
SESSION_SECRET = str(_read(ROOT_CONFIG, "admin", "session_secret", default="thermocalc-session-secret-change-me"))
LOW_BATTERY_THRESHOLD_PERCENT = int(_read(ROOT_CONFIG, "alerts", "low_battery_threshold_percent", default=10))
ALERT_EMAIL_TO = str(_read(ROOT_CONFIG, "alerts", "email_to", default=""))
ALERT_EMAIL_FROM = str(_read(ROOT_CONFIG, "alerts", "email_from", default="thermocalc@localhost"))
SMTP_HOST = str(_read(ROOT_CONFIG, "smtp", "host", default=""))
SMTP_PORT = int(_read(ROOT_CONFIG, "smtp", "port", default=587))
SMTP_USERNAME = str(_read(ROOT_CONFIG, "smtp", "username", default=""))
SMTP_PASSWORD = str(_read(ROOT_CONFIG, "smtp", "password", default=""))
SMTP_USE_TLS = bool(_read(ROOT_CONFIG, "smtp", "use_tls", default=True))
