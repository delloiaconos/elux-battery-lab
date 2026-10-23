"""Load and validate application configuration."""

from __future__ import annotations

import configparser
import math
from pathlib import Path

from battery_cycler.core.models import AppConfig, ConfigurationError


def _positive_config_float(
    values: configparser.SectionProxy, key: str, config_path: Path
) -> float:
    try:
        value = values.getfloat(key)
    except (ValueError, configparser.Error) as exc:
        raise ConfigurationError(
            f"{config_path}: {key!r} must be a number"
        ) from exc
    if value is None or not math.isfinite(value) or value <= 0.0:
        raise ConfigurationError(f"{config_path}: {key!r} must be finite and > 0")
    return value


def load_config(config_path: Path) -> AppConfig:
    """Load and validate the human-readable INI configuration."""
    parser = configparser.ConfigParser(interpolation=None)
    try:
        read_files = parser.read(config_path, encoding="utf-8")
    except configparser.Error as exc:
        raise ConfigurationError(f"Unable to parse {config_path}: {exc}") from exc
    if not read_files:
        raise ConfigurationError(f"Configuration file not found: {config_path}")

    values = parser["DEFAULT"]
    required = (
        "dev-address",
        "dev-port",
        "in-dir",
        "out-dir",
        "sampling-time",
        "voltage-compliance",
        "current-compliance",
    )
    missing = [key for key in required if not values.get(key, "").strip()]
    if missing:
        raise ConfigurationError(
            f"{config_path}: missing required setting(s): {', '.join(missing)}"
        )

    try:
        dev_port = values.getint("dev-port")
    except (ValueError, configparser.Error) as exc:
        raise ConfigurationError(f"{config_path}: 'dev-port' must be an integer") from exc
    if dev_port is None or not 1 <= dev_port <= 65535:
        raise ConfigurationError(f"{config_path}: 'dev-port' must be in 1..65535")

    return AppConfig(
        dev_address=values["dev-address"].strip(),
        dev_port=dev_port,
        in_dir=Path(values["in-dir"]).expanduser(),
        out_dir=Path(values["out-dir"]).expanduser(),
        sampling_time=_positive_config_float(values, "sampling-time", config_path),
        voltage_compliance=_positive_config_float(
            values, "voltage-compliance", config_path
        ),
        current_compliance=_positive_config_float(
            values, "current-compliance", config_path
        ),
    )
