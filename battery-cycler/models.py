"""Shared data models, constants, and application exceptions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


CSV_COLUMNS = (
    "duration",
    "mode",
    "source",
    "compliance",
    "meas_lb",
    "meas_up",
    "epsilon",
    "tcompliance",
)
OUTPUT_COLUMNS = ("timestamp", "idphase", "state", "current", "voltage")
SOCKET_TIMEOUT_SECONDS = 5.0


class ConfigurationError(ValueError):
    """Raised when configuration or command-line values are invalid."""


class InputFileError(ValueError):
    """Raised when the test profile is invalid."""


class InstrumentError(RuntimeError):
    """Raised when communication with the instrument fails."""


class TerminationRequested(BaseException):
    """Raised when the operating system requests process termination."""

    def __init__(self, signum: int) -> None:
        super().__init__(signum)
        self.signum = signum


@dataclass(frozen=True)
class AppConfig:
    dev_address: str
    dev_port: int
    in_dir: Path
    out_dir: Path
    sampling_time: float
    voltage_compliance: float
    current_compliance: float


@dataclass(frozen=True)
class TestStep:
    duration: float
    mode: str
    source: float | None = None
    compliance: float | None = None
    meas_lb: float | None = None
    meas_up: float | None = None
    epsilon: float | None = None
    tcompliance: float | None = None


@dataclass(frozen=True)
class Measurement:
    current: float
    voltage: float
    state: str


def require_step_value(step: TestStep, attribute: str) -> float:
    """Return a validated optional step value used by an executable phase."""
    value = getattr(step, attribute)
    if value is None:
        raise RuntimeError(f"Internal error: {attribute} missing for {step.mode} step")
    return value
