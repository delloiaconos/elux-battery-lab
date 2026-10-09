"""Load, validate, and summarize battery-test profile CSV files."""

from __future__ import annotations

import csv
import math
import statistics
from pathlib import Path

from models import CSV_COLUMNS, InputFileError, TestStep


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
