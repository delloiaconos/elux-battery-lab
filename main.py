#!/usr/bin/env python3
"""Run battery test profiles on a Keithley 2461 over raw SCPI/TCP."""

from __future__ import annotations

import argparse
import configparser
import csv
import math
import signal
import socket
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence


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
_termination_in_progress = False


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


def _managed_termination_signals() -> tuple[signal.Signals, ...]:
    managed = [signal.SIGTERM]
    if hasattr(signal, "SIGHUP"):
        managed.append(signal.SIGHUP)
    return tuple(managed)


def _handle_termination_signal(signum: int, _frame: object) -> None:
    global _termination_in_progress
    if _termination_in_progress:
        return
    _termination_in_progress = True
    raise TerminationRequested(signum)


def _install_termination_handlers() -> dict[signal.Signals, object]:
    global _termination_in_progress
    _termination_in_progress = False
    previous_handlers: dict[signal.Signals, object] = {}
    for managed_signal in _managed_termination_signals():
        previous_handlers[managed_signal] = signal.getsignal(managed_signal)
        signal.signal(managed_signal, _handle_termination_signal)
    return previous_handlers


def _restore_termination_handlers(
    previous_handlers: dict[signal.Signals, object],
) -> None:
    for managed_signal, previous_handler in previous_handlers.items():
        signal.signal(managed_signal, previous_handler)


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


class ScpiClient:
    """Line-oriented SCPI client for the instrument raw TCP socket."""

    def __init__(self, address: str, port: int) -> None:
        self.address = address
        self.port = port
        self._socket: socket.socket | None = None
        self._reader = None

    def connect(self) -> None:
        try:
            self._socket = socket.create_connection(
                (self.address, self.port), timeout=SOCKET_TIMEOUT_SECONDS
            )
            self._socket.settimeout(SOCKET_TIMEOUT_SECONDS)
            self._reader = self._socket.makefile("r", encoding="ascii", newline="\n")
        except OSError as exc:
            self.close()
            raise InstrumentError(
                f"Unable to connect to {self.address}:{self.port}: {exc}"
            ) from exc

    def send(self, command: str) -> None:
        if self._socket is None:
            raise InstrumentError("SCPI socket is not connected")
        try:
            self._socket.sendall((command + "\n").encode("ascii"))
        except OSError as exc:
            raise InstrumentError(f"Failed to send SCPI command {command!r}: {exc}") from exc

    def query(self, command: str) -> str:
        if self._reader is None:
            raise InstrumentError("SCPI socket is not connected")
        self.send(command)
        try:
            response = self._reader.readline()
        except OSError as exc:
            raise InstrumentError(f"Failed to read response to {command!r}: {exc}") from exc
        if response == "":
            raise InstrumentError(f"Instrument closed the connection after {command!r}")
        return response.strip()

    def close(self) -> None:
        if self._reader is not None:
            try:
                self._reader.close()
            except OSError:
                pass
            self._reader = None
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None


def _finite_float(value: str, field: str, row_number: int) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise InputFileError(
            f"Row {row_number}: {field!r} must be a number, got {value!r}"
        ) from exc
    if not math.isfinite(parsed):
        raise InputFileError(f"Row {row_number}: {field!r} must be finite")
    return parsed


def _required_float(row: dict[str, str], field: str, row_number: int) -> float:
    value = row.get(field, "")
    if not value:
        raise InputFileError(f"Row {row_number}: {field!r} is required")
    return _finite_float(value, field, row_number)


def _print_source_summary(label: str, unit: str, values: list[float]) -> None:
    if not values:
        print(f"  {label}: n/a")
        return
    print(
        f"  {label}: min={min(values):.9g} {unit}, "
        f"max={max(values):.9g} {unit}, mean={statistics.fmean(values):.9g} {unit}"
    )


def input_parsing(input_path: Path) -> list[TestStep]:
    """Parse and validate a test-profile CSV, then print its summary."""
    try:
        input_file = input_path.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise InputFileError(f"Unable to open input file {input_path}: {exc}") from exc

    steps: list[TestStep] = []
    with input_file:
        reader = csv.DictReader(input_file, skipinitialspace=True)
        if reader.fieldnames is None:
            raise InputFileError("The input CSV is empty or has no header")

        normalized_header = tuple(name.strip() for name in reader.fieldnames)
        if normalized_header != CSV_COLUMNS:
            expected = ",".join(CSV_COLUMNS)
            actual = ",".join(normalized_header)
            raise InputFileError(
                f"Invalid CSV header. Expected {expected!r}, got {actual!r}"
            )

        for row_number, raw_row in enumerate(reader, start=2):
            row = {
                key.strip(): (value.strip() if value is not None else "")
                for key, value in raw_row.items()
                if key is not None
            }
            if not any(row.values()):
                continue

            mode = row.get("mode", "").upper()
            if mode not in {"CURR", "VOLT", "MEAS", "STOP"}:
                raise InputFileError(
                    f"Row {row_number}: mode must be CURR, VOLT, MEAS, or STOP"
                )

            if mode == "STOP":
                steps.append(TestStep(duration=0.0, mode=mode))
                continue

            duration = _required_float(row, "duration", row_number)
            if duration < 0.0 and duration != -1.0:
                raise InputFileError(
                    f"Row {row_number}: duration must be non-negative or exactly -1"
                )

            if mode == "MEAS":
                if duration == -1.0:
                    raise InputFileError(
                        f"Row {row_number}: MEAS cannot use duration=-1 because "
                        "MEAS has no compliance termination condition"
                    )
                steps.append(TestStep(duration=duration, mode=mode))
                continue

            source = _required_float(row, "source", row_number)
            compliance = _required_float(row, "compliance", row_number)
            meas_lb = _required_float(row, "meas_lb", row_number)
            meas_up = _required_float(row, "meas_up", row_number)
            epsilon = _required_float(row, "epsilon", row_number)
            tcompliance = _required_float(row, "tcompliance", row_number)

            if compliance <= 0.0:
                raise InputFileError(f"Row {row_number}: compliance must be > 0")
            if meas_lb > meas_up:
                raise InputFileError(f"Row {row_number}: meas_lb must be <= meas_up")
            if epsilon <= 0.0:
                raise InputFileError(f"Row {row_number}: epsilon must be > 0")
            if tcompliance < 0.0:
                raise InputFileError(f"Row {row_number}: tcompliance must be >= 0")

            steps.append(
                TestStep(
                    duration=duration,
                    mode=mode,
                    source=source,
                    compliance=compliance,
                    meas_lb=meas_lb,
                    meas_up=meas_up,
                    epsilon=epsilon,
                    tcompliance=tcompliance,
                )
            )

    if not steps:
        raise InputFileError("The input CSV contains no test steps")

    finite_duration = sum(step.duration for step in steps if step.duration >= 0.0)
    current_sources = [step.source for step in steps if step.mode == "CURR"]
    voltage_sources = [step.source for step in steps if step.mode == "VOLT"]

    print(f"Input profile: {input_path}")
    print(f"  Steps: {len(steps)}")
    print(f"  Finite total duration: {finite_duration / 60.0:.3f} min")
    _print_source_summary(
        "CURR source", "A", [value for value in current_sources if value is not None]
    )
    _print_source_summary(
        "VOLT source", "V", [value for value in voltage_sources if value is not None]
    )
    return steps


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


def setup(config: AppConfig) -> ScpiClient:
    """Connect, identify, reset, and place the 2461 in a safe output-off state."""
    client = ScpiClient(config.dev_address, config.dev_port)
    print(f"Connecting to Keithley 2461 at {config.dev_address}:{config.dev_port}...")
    connected = False
    try:
        client.connect()
        connected = True
        identification = client.query("*IDN?")
        idn_upper = identification.upper()
        if "KEITHLEY" not in idn_upper or "MODEL 2461" not in idn_upper:
            raise InstrumentError(
                "Unexpected instrument identity: "
                f"{identification!r}; expected a Keithley 2461"
            )
        print(f"Instrument: {identification}")

        client.send("*RST")
        if client.query("*OPC?") != "1":
            raise InstrumentError("Instrument did not acknowledge reset completion")
        client.send(":TRIG:CONT OFF")
        client.send(":OUTP:SMOD HIMP")
        client.send(":OUTP OFF")

        client.send(":SENS:VOLT:RSEN ON")
        client.send(":SENS:CURR:RSEN ON")
        for query in (":SENS:VOLT:RSEN?", ":SENS:CURR:RSEN?"):
            if not _parse_scpi_bool(client.query(query), query):
                raise InstrumentError(
                    f"Instrument did not enable four-wire sensing ({query})"
                )
        return client
    except BaseException:
        if connected:
            try:
                shutdown(client)
            except Exception as shutdown_error:
                print(
                    f"ERROR during setup shutdown: {shutdown_error}",
                    file=sys.stderr,
                )
        else:
            client.close()
        raise


def shutdown(client: ScpiClient | None) -> None:
    """Best-effort safe shutdown; all commands are attempted before closing TCP."""
    if client is None:
        return

    errors: list[str] = []
    for command in (
        ":TRIG:CONT OFF",
        ":OUTP:SMOD HIMP",
        ":OUTP OFF",
        ":TRIG:CONT AUTO",
    ):
        try:
            client.send(command)
        except Exception as exc:  # Continue so later safety actions are still attempted.
            errors.append(f"{command}: {exc}")
    client.close()
    print(
        "Instrument triggering stopped, output set to high impedance and "
        "switched off; TCP closed."
    )
    if errors:
        raise InstrumentError("Shutdown was incomplete: " + "; ".join(errors))


def _require_step_value(step: TestStep, attribute: str) -> float:
    value = getattr(step, attribute)
    if value is None:
        raise RuntimeError(f"Internal error: {attribute} missing for {step.mode} step")
    return value


def _configure_step(client: ScpiClient, config: AppConfig, step: TestStep) -> float | None:
    client.send(":OUTP:SMOD HIMP")
    client.send(":OUTP OFF")

    if step.mode == "MEAS":
        client.send(":SOUR:FUNC CURR")
        client.send(":SOUR:CURR:RANG:AUTO ON")
        client.send(f":SOUR:CURR:VLIM {config.voltage_compliance:.12g}")
        client.send(":SOUR:CURR:READ:BACK ON")
        client.send(':SENS:FUNC "VOLT"')
        client.send(":SENS:VOLT:RANG:AUTO ON")
        client.send(":SOUR:CURR 0")
        client.send(":OUTP ON")
        return None

    source = _require_step_value(step, "source")
    requested_compliance = _require_step_value(step, "compliance")

    if step.mode == "CURR":
        applied_compliance = min(requested_compliance, config.voltage_compliance)
        client.send(":SOUR:FUNC CURR")
        client.send(":SOUR:CURR:RANG:AUTO ON")
        client.send(f":SOUR:CURR:VLIM {applied_compliance:.12g}")
        client.send(":SOUR:CURR:READ:BACK ON")
        client.send(':SENS:FUNC "VOLT"')
        client.send(":SENS:VOLT:RANG:AUTO ON")
        client.send(f":SOUR:CURR {source:.12g}")
    else:
        applied_compliance = min(requested_compliance, config.current_compliance)
        client.send(":SOUR:FUNC VOLT")
        client.send(":SOUR:VOLT:RANG:AUTO ON")
        client.send(f":SOUR:VOLT:ILIM {applied_compliance:.12g}")
        client.send(":SOUR:VOLT:READ:BACK ON")
        client.send(':SENS:FUNC "CURR"')
        client.send(":SENS:CURR:RANG:AUTO ON")
        client.send(f":SOUR:VOLT {source:.12g}")

    client.send(":OUTP ON")
    return applied_compliance


def _parse_float_response(response: str, command: str) -> float:
    try:
        value = float(response.split(",", maxsplit=1)[0])
    except ValueError as exc:
        raise InstrumentError(
            f"Invalid numeric response to {command!r}: {response!r}"
        ) from exc
    if not math.isfinite(value):
        raise InstrumentError(f"Non-finite response to {command!r}: {response!r}")
    return value


def _parse_pair_response(response: str, command: str) -> tuple[float, float]:
    fields = response.split(",")
    if len(fields) != 2:
        raise InstrumentError(
            f"Expected two values from {command!r}, got {response!r}"
        )
    return (
        _parse_float_response(fields[0], command),
        _parse_float_response(fields[1], command),
    )


def _parse_scpi_bool(response: str, command: str) -> bool:
    normalized = response.strip().upper()
    if normalized in {"1", "ON", "TRUE"}:
        return True
    if normalized in {"0", "OFF", "FALSE"}:
        return False
    raise InstrumentError(f"Invalid Boolean response to {command!r}: {response!r}")


def _measure(client: ScpiClient, mode: str) -> Measurement:
    read_command = ':READ? "defbuffer1", SOUR, READ'
    source_value, measured_value = _parse_pair_response(
        client.query(read_command), read_command
    )

    if mode == "MEAS":
        return Measurement(
            current=source_value,
            voltage=measured_value,
            state="MEAS",
        )

    if mode == "CURR":
        trip_command = ":SOUR:CURR:VLIM:TRIP?"
        tripped = _parse_scpi_bool(client.query(trip_command), trip_command)
        return Measurement(
            current=source_value,
            voltage=measured_value,
            state="VLIM" if tripped else "CURR",
        )

    trip_command = ":SOUR:VOLT:ILIM:TRIP?"
    tripped = _parse_scpi_bool(client.query(trip_command), trip_command)
    return Measurement(
        current=measured_value,
        voltage=source_value,
        state="ILIM" if tripped else "VOLT",
    )


def _outside_measurement_limits(step: TestStep, measurement: Measurement) -> bool:
    if step.mode == "MEAS":
        return False
    lower = _require_step_value(step, "meas_lb")
    upper = _require_step_value(step, "meas_up")
    controlled_measurement = (
        measurement.voltage if step.mode == "CURR" else measurement.current
    )
    return not lower <= controlled_measurement <= upper


def _run_step(
    client: ScpiClient,
    writer: csv.writer,
    output_file,
    config: AppConfig,
    step: TestStep,
    phase_id: int,
) -> None:
    applied_compliance = _configure_step(client, config, step)
    print(
        f"Step {phase_id}: mode={step.mode}, duration={step.duration:g} s"
        + (
            ""
            if applied_compliance is None
            else f", applied compliance={applied_compliance:.9g}"
        )
    )

    started_at = time.monotonic()
    next_sample_at = started_at
    compliance_started_at: float | None = None

    while True:
        now = time.monotonic()
        if step.duration >= 0.0 and now - started_at >= step.duration:
            print(f"Step {phase_id}: duration reached")
            return

        if now < next_sample_at:
            time.sleep(next_sample_at - now)

        measurement = _measure(client, step.mode)
        sampled_at = time.monotonic()
        timestamp = f"{time.time():.3f}"
        writer.writerow(
            (
                timestamp,
                phase_id,
                measurement.state,
                f"{measurement.current:.12g}",
                f"{measurement.voltage:.12g}",
            )
        )
        output_file.flush()
        print(
            f"[{timestamp}] phase={phase_id} state={measurement.state} "
            f"I={measurement.current:.9g} A V={measurement.voltage:.9g} V"
        )

        if step.duration >= 0.0:
            if _outside_measurement_limits(step, measurement):
                print(f"Step {phase_id}: measurement outside limits; advancing")
                return
        else:
            tripped = measurement.state in {"VLIM", "ILIM"}
            if tripped:
                if compliance_started_at is None:
                    compliance_started_at = sampled_at

                measured_limit_value = (
                    measurement.voltage
                    if step.mode == "CURR"
                    else measurement.current
                )
                epsilon = _require_step_value(step, "epsilon")
                if abs(abs(measured_limit_value) - float(applied_compliance)) <= epsilon:
                    print(f"Step {phase_id}: compliance value reached within epsilon")
                    return

                tcompliance = _require_step_value(step, "tcompliance")
                if sampled_at - compliance_started_at >= tcompliance:
                    print(f"Step {phase_id}: compliance time limit reached")
                    return
            else:
                compliance_started_at = None

        next_sample_at = max(
            next_sample_at + config.sampling_time, time.monotonic()
        )


def testing(
    client: ScpiClient,
    config: AppConfig,
    steps: Sequence[TestStep],
    output_path: Path,
) -> None:
    """Execute all profile steps and stream measurements to the output CSV."""
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_file = output_path.open("w", encoding="utf-8", newline="")
    except OSError as exc:
        raise ConfigurationError(f"Unable to create output file {output_path}: {exc}") from exc

    print(f"Writing measurements to {output_path}")
    with output_file:
        writer = csv.writer(output_file)
        writer.writerow(OUTPUT_COLUMNS)
        output_file.flush()
        for phase_id, step in enumerate(steps, start=1):
            if step.mode == "STOP":
                print(f"Step {phase_id}: STOP requested")
                break
            _run_step(client, writer, output_file, config, step, phase_id)


def run_test(config: AppConfig, steps: Sequence[TestStep], output_path: Path) -> None:
    """Run setup, testing, and guaranteed shutdown."""
    client: ScpiClient | None = None
    active_error: BaseException | None = None
    try:
        client = setup(config)
        testing(client, config, steps, output_path)
    except BaseException as exc:
        active_error = exc
        raise
    finally:
        try:
            shutdown(client)
        except Exception as shutdown_error:
            if active_error is None:
                raise
            print(f"ERROR during shutdown: {shutdown_error}", file=sys.stderr)


def _check_device(config: AppConfig) -> None:
    client: ScpiClient | None = None
    active_error: BaseException | None = None
    try:
        client = setup(config)
        print("Device check passed.")
    except BaseException as exc:
        active_error = exc
        raise
    finally:
        try:
            shutdown(client)
        except Exception as shutdown_error:
            if active_error is None:
                raise
            print(f"ERROR during shutdown: {shutdown_error}", file=sys.stderr)


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run CSV battery-test profiles on a Keithley 2461 over SCPI/TCP."
    )
    parser.add_argument("--config", default="config.ini", help="INI configuration file")
    parser.add_argument("--in-file", default="steps.csv", help="input profile CSV name")
    parser.add_argument("--in-dir", help="override the input directory from config.ini")
    parser.add_argument(
        "--out-name",
        help="output CSV name (default: YYYYMMDDTHHMM_output.csv)",
    )
    parser.add_argument("--out-dir", help="override the output directory from config.ini")
    checks = parser.add_mutually_exclusive_group()
    checks.add_argument(
        "--check-input",
        action="store_true",
        help="validate and summarize input without connecting to the instrument",
    )
    checks.add_argument(
        "--check-dev",
        action="store_true",
        help="run setup and shutdown only",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    previous_handlers = _install_termination_handlers()
    try:
        args = _build_argument_parser().parse_args(argv)
        try:
            config = load_config(Path(args.config))
            in_dir = Path(args.in_dir).expanduser() if args.in_dir else config.in_dir
            out_dir = Path(args.out_dir).expanduser() if args.out_dir else config.out_dir
            input_path = in_dir / args.in_file

            if args.check_dev:
                _check_device(config)
                return 0

            steps = input_parsing(input_path)
            if args.check_input:
                return 0

            output_name = args.out_name or datetime.now().strftime(
                "%Y%m%dT%H%M_output.csv"
            )
            output_path = out_dir / output_name
            run_test(config, steps, output_path)
            return 0
        except TerminationRequested as exc:
            try:
                signal_name = signal.Signals(exc.signum).name
            except ValueError:
                signal_name = str(exc.signum)
            print(
                f"\nTermination signal {signal_name} received; shutdown attempted.",
                file=sys.stderr,
            )
            return 128 + exc.signum
        except KeyboardInterrupt:
            print("\nTest interrupted by user; shutdown attempted.", file=sys.stderr)
            return 130
        except (ConfigurationError, InputFileError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        except (InstrumentError, OSError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    finally:
        _restore_termination_handlers(previous_handlers)


if __name__ == "__main__":
    raise SystemExit(main())
