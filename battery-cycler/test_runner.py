"""Battery-test execution engine, independent from CLI and file parsing."""

from __future__ import annotations

import csv
import sys
import time
from pathlib import Path
from typing import Sequence

from instrument import ScpiClient, configure_step, measure, setup, shutdown
from models import (
    AppConfig,
    ConfigurationError,
    Measurement,
    OUTPUT_COLUMNS,
    TestStep,
    require_step_value,
)


def _outside_measurement_limits(step: TestStep, measurement: Measurement) -> bool:
    if step.mode == "MEAS":
        return False
    lower = require_step_value(step, "meas_lb")
    upper = require_step_value(step, "meas_up")
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
    applied_compliance = configure_step(client, config, step)
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

        measurement = measure(client, step.mode)
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
                epsilon = require_step_value(step, "epsilon")
                if abs(abs(measured_limit_value) - float(applied_compliance)) <= epsilon:
                    print(f"Step {phase_id}: compliance value reached within epsilon")
                    return

                tcompliance = require_step_value(step, "tcompliance")
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
    """Run instrument setup, battery testing, and guaranteed shutdown."""
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
