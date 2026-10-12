"""Battery-test execution engine, independent from CLI and file parsing."""

from __future__ import annotations

import csv
import json
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


def _format_elapsed(seconds: float) -> str:
    """Format elapsed seconds as HH:MM:SS.mmm for console progress."""
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{int(hours):02d}:{int(minutes):02d}:{seconds:06.3f}"


def _run_step(
    client: ScpiClient,
    writer: csv.writer,
    output_file,
    config: AppConfig,
    step: TestStep,
    phase_id: int,
    run_started_at: float,
) -> None:
    applied_compliance = configure_step(client, config, step)
    print(
        f"[{_format_elapsed(time.monotonic() - run_started_at)}] "
        f"Step {phase_id}: mode={step.mode}, duration={step.duration:g} s"
        + (
            ""
            if applied_compliance is None
            else f", applied compliance={applied_compliance:.9g}"
        ),
        file=sys.stderr,
    )

    started_at = time.monotonic()
    next_sample_at = started_at
    compliance_t = require_step_value(step, "compliance_t")
    compliance_started_at: float | None = None

    while True:
        now = time.monotonic()
        if step.duration >= 0.0 and now - started_at >= step.duration:
            print(
                f"[{_format_elapsed(time.monotonic() - run_started_at)}] "
                f"Step {phase_id}: duration reached",
                file=sys.stderr,
            )
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
            json.dumps(
                {
                    "time": round(sampled_at - run_started_at, 3),
                    "timestamp": float(timestamp),
                    "idphase": phase_id,
                    "state": measurement.state,
                    "current": measurement.current,
                    "voltage": measurement.voltage,
                },
                separators=(",", ":"),
                allow_nan=False,
            )
        )

        if step.duration >= 0.0:
            if _outside_measurement_limits(step, measurement):
                print(
                    f"[{_format_elapsed(time.monotonic() - run_started_at)}] "
                    f"Step {phase_id}: measurement outside limits; advancing",
                    file=sys.stderr,
                )
                return
            
            tripped = measurement.state in {"VLIM", "ILIM"}
            if tripped:
                if compliance_started_at is None:
                    compliance_started_at = sampled_at
                
                if (
                    compliance_t is not None
                    and sampled_at - compliance_started_at >= compliance_t
                ):
                    print(
                        f"[{_format_elapsed(time.monotonic() - run_started_at)}] "
                        f"Step {phase_id}: compliance time limit reached",
                        file=sys.stderr,
                    )
                    return

                if measurement.state == "VLIM":
                    if abs( measurement.current ) < step.compliance_lim:
                        print(
                            f"[{_format_elapsed(time.monotonic() - run_started_at)}] "
                            f"Step {phase_id}: current compliance_lim exceeded",
                            file=sys.stderr,
                        )
                        return
                elif measurement.state == "ILIM":
                    if abs( measurement.voltage ) < step.compliance_lim:
                        print(
                            f"[{_format_elapsed(time.monotonic() - run_started_at)}] "
                            f"Step {phase_id}: voltage compliance_lim exceeded",
                            file=sys.stderr,
                        )
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
    run_started_at: float,
) -> None:
    """Execute all profile steps and stream measurements to the output CSV."""
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_file = output_path.open("w", encoding="utf-8", newline="")
    except OSError as exc:
        raise ConfigurationError(f"Unable to create output file {output_path}: {exc}") from exc

    print(f"Writing measurements to {output_path}", file=sys.stderr)
    with output_file:
        writer = csv.writer(output_file)
        writer.writerow(OUTPUT_COLUMNS)
        output_file.flush()
        for phase_id, step in enumerate(steps, start=1):
            if step.mode == "STOP":
                print(
                    f"[{_format_elapsed(time.monotonic() - run_started_at)}] "
                    f"Step {phase_id}: STOP requested",
                    file=sys.stderr,
                )
                break
            _run_step(
                client, writer, output_file, config, step, phase_id, run_started_at
            )


def run_test(config: AppConfig, steps: Sequence[TestStep], output_path: Path) -> None:
    """Run instrument setup, battery testing, and guaranteed shutdown."""
    client: ScpiClient | None = None
    active_error: BaseException | None = None
    run_started_at = time.monotonic()
    try:
        client = setup(config)
        testing(client, config, steps, output_path, run_started_at)
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
