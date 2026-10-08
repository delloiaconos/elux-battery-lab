"""Display the programmed test profile and acquired Keithley measurements."""

from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt


SECONDS_PER_HOUR = 3600.0


class PlotInputError(ValueError):
    """Raised when an input CSV cannot be plotted safely."""


@dataclass(frozen=True)
class ProfileSegment:
    start: float
    end: float
    mode: str
    source: float | None


@dataclass(frozen=True)
class Measurement:
    timestamp: float
    current: float
    voltage: float


def _finite_float(value: str, field: str, row_number: int, path: Path) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise PlotInputError(
            f"{path}: row {row_number}: {field!r} must be numeric"
        ) from exc
    if not math.isfinite(result):
        raise PlotInputError(
            f"{path}: row {row_number}: {field!r} must be finite"
        )
    return result


def _open_dict_reader(path: Path) -> tuple[object, csv.DictReader]:
    try:
        stream = path.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise PlotInputError(f"Unable to open {path}: {exc}") from exc
    reader = csv.DictReader(stream, skipinitialspace=True)
    if reader.fieldnames is None:
        stream.close()
        raise PlotInputError(f"{path}: CSV is empty or has no header")
    reader.fieldnames = [name.strip() for name in reader.fieldnames]
    return stream, reader


def _require_columns(
    fieldnames: Iterable[str], required: set[str], path: Path
) -> None:
    missing = sorted(required.difference(fieldnames))
    if missing:
        raise PlotInputError(f"{path}: missing columns: {', '.join(missing)}")


def load_profile(path: Path) -> list[ProfileSegment]:
    """Load finite profile steps; STOP and duration=-1 rows are discarded."""
    stream, reader = _open_dict_reader(path)
    with stream:
        _require_columns(reader.fieldnames or (), {"duration", "mode", "source"}, path)
        segments: list[ProfileSegment] = []
        elapsed = 0.0

        for row_number, raw_row in enumerate(reader, start=2):
            row = {
                key.strip(): (value.strip() if value is not None else "")
                for key, value in raw_row.items()
                if key is not None
            }
            if not any(row.values()):
                continue

            mode = row["mode"].upper()
            if mode == "STOP":
                break
            if mode not in {"CURR", "VOLT", "MEAS"}:
                raise PlotInputError(
                    f"{path}: row {row_number}: unsupported mode {mode!r}"
                )

            duration = _finite_float(row["duration"], "duration", row_number, path)
            if duration == -1.0:
                continue
            if duration < 0.0:
                raise PlotInputError(
                    f"{path}: row {row_number}: duration must be >= 0 or -1"
                )

            source: float | None = None
            if mode in {"CURR", "VOLT"}:
                source = _finite_float(row["source"], "source", row_number, path)

            segments.append(ProfileSegment(elapsed, elapsed + duration, mode, source))
            elapsed += duration

    if not segments:
        raise PlotInputError(f"{path}: no finite test steps to plot")
    return segments


def load_measurements(path: Path) -> list[Measurement]:
    """Load measurement time, current, and voltage from a runner output CSV."""
    stream, reader = _open_dict_reader(path)
    with stream:
        _require_columns(
            reader.fieldnames or (), {"timestamp", "current", "voltage"}, path
        )
        measurements: list[Measurement] = []
        for row_number, raw_row in enumerate(reader, start=2):
            row = {
                key.strip(): (value.strip() if value is not None else "")
                for key, value in raw_row.items()
                if key is not None
            }
            if not any(row.values()):
                continue
            measurements.append(
                Measurement(
                    timestamp=_finite_float(
                        row["timestamp"], "timestamp", row_number, path
                    ),
                    current=_finite_float(row["current"], "current", row_number, path),
                    voltage=_finite_float(row["voltage"], "voltage", row_number, path),
                )
            )

    if not measurements:
        raise PlotInputError(f"{path}: no measurements to plot")
    if any(
        current.timestamp < previous.timestamp
        for previous, current in zip(measurements, measurements[1:])
    ):
        raise PlotInputError(f"{path}: timestamps are not monotonically increasing")
    return measurements


def _combined_legend(ax_left, ax_right, location: str = "best") -> None:
    lines = ax_left.get_lines() + ax_right.get_lines()
    if lines:
        ax_left.legend(lines, [line.get_label() for line in lines], loc=location)


def _draw_profile(ax_current, segments: list[ProfileSegment]) -> None:
    ax_voltage = ax_current.twinx()

    current_label_added = False
    voltage_label_added = False
    for segment in segments:
        start_hours = segment.start / SECONDS_PER_HOUR
        end_hours = segment.end / SECONDS_PER_HOUR
        if segment.mode == "CURR":
            ax_current.plot(
                [start_hours, end_hours],
                [segment.source, segment.source],
                color="tab:blue",
                linewidth=2,
                label="Programmed current" if not current_label_added else "_nolegend_",
            )
            current_label_added = True
        elif segment.mode == "VOLT":
            ax_voltage.plot(
                [start_hours, end_hours],
                [segment.source, segment.source],
                color="tab:red",
                linewidth=2,
                label="Programmed voltage" if not voltage_label_added else "_nolegend_",
            )
            voltage_label_added = True

    ax_current.set_title("Test profile")
    ax_current.set_xlabel("Time [h]")
    ax_current.set_ylabel("Current [A]", color="tab:blue")
    ax_voltage.set_ylabel("Voltage [V]", color="tab:red")
    ax_current.tick_params(axis="y", labelcolor="tab:blue")
    ax_voltage.tick_params(axis="y", labelcolor="tab:red")
    profile_end = max(segment.end for segment in segments) / SECONDS_PER_HOUR
    ax_current.set_xlim(0.0, profile_end if profile_end > 0.0 else 1.0)
    ax_current.grid(True, alpha=0.3)
    #_combined_legend(ax_current, ax_voltage)


def plot_profile(segments: list[ProfileSegment]) -> None:
    fig, ax_current = plt.subplots(num="Test profile", clear=True)
    _draw_profile(ax_current, segments)
    fig.tight_layout()


def _draw_measurements(ax_current, measurements: list[Measurement]) -> None:
    initial_timestamp = measurements[0].timestamp
    elapsed = [
        (item.timestamp - initial_timestamp) / SECONDS_PER_HOUR
        for item in measurements
    ]
    current = [item.current for item in measurements]
    voltage = [item.voltage for item in measurements]

    ax_voltage = ax_current.twinx()
    ax_current.plot(elapsed, current, color="tab:blue", label="Current")
    ax_voltage.plot(elapsed, voltage, color="tab:red", label="Voltage")

    ax_current.set_title("Measured current and voltage")
    ax_current.set_xlabel("Time [h]")
    ax_current.set_ylabel("Current [A]", color="tab:blue")
    ax_voltage.set_ylabel("Voltage [V]", color="tab:red")
    ax_current.tick_params(axis="y", labelcolor="tab:blue")
    ax_voltage.tick_params(axis="y", labelcolor="tab:red")
    ax_current.set_xlim(left=0.0)
    ax_current.grid(True, alpha=0.3)
    #_combined_legend(ax_current, ax_voltage)


def plot_measurements(measurements: list[Measurement]) -> None:
    fig, ax_current = plt.subplots(num="Measurements", clear=True)
    _draw_measurements(ax_current, measurements)
    fig.tight_layout()


def save_output(
    segments: list[ProfileSegment],
    measurements: list[Measurement],
    output_path: Path,
) -> Path:
    """Save both plots in one image and return its absolute path."""
    output_path = output_path.expanduser()
    if not output_path.is_absolute():
        output_path = Path.cwd() / output_path
    if not output_path.suffix:
        output_path = output_path.with_suffix(".png")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(2, 1, figsize=(12, 9), layout="constrained")
    _draw_profile(axes[0], segments)
    _draw_measurements(axes[1], measurements)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot a battery-test profile and its acquired measurements."
    )
    parser.add_argument(
        "--file-step",
        required=True,
        type=Path,
        help="test-profile CSV file",
    )
    parser.add_argument(
        "--file-measures",
        required=True,
        type=Path,
        help="measurement-output CSV file",
    )
    parser.add_argument(
        "--output",
        nargs="?",
        const=Path("."),
        type=Path,
        metavar="IMAGE",
        help=(
            "save both plots in one image; if IMAGE is omitted, use the "
            "measurement filename with a .png extension in the current directory"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        segments = load_profile(args.file_step)
        measurements = load_measurements(args.file_measures)
    except PlotInputError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc

    if args.output is not None:
        if args.output == Path(".") or args.output.is_dir():
            output_path = (
                args.output / args.file_measures.with_suffix(".png").name
            )
        else:
            output_path = args.output
        try:
            output_path = save_output(segments, measurements, output_path)
        except (OSError, ValueError) as exc:
            raise SystemExit(f"ERROR: unable to save plot: {exc}") from exc
        print(f"Saved plot: {output_path}")
    else:
        plot_profile(segments)
        plot_measurements(measurements)
        plt.show()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
