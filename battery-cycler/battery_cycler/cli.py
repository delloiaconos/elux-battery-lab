#!/usr/bin/env python3
"""Command-line entry point for Keithley 2461 battery testing."""

from __future__ import annotations

import argparse
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

from battery_cycler.instruments.keithley2461 import ScpiClient, setup, shutdown
from battery_cycler.core.models import (
    AppConfig,
    ConfigurationError,
    InputFileError,
    InstrumentError,
    TerminationRequested,
)
from battery_cycler.config import load_config
from battery_cycler.profiles.parser import input_parsing
from battery_cycler.core.runner import run_test


_termination_in_progress = False


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


def _check_device(config: AppConfig) -> None:
    client: ScpiClient | None = None
    active_error: BaseException | None = None
    try:
        client = setup(config)
        print("Device check passed.", file=sys.stderr)
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
    parser.add_argument("--input", default="steps.csv", help="input profile CSV name")
    parser.add_argument("--in-dir", help="override the input directory from config.ini")
    parser.add_argument(
        "--output",
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
            input_path = in_dir / args.input

            if args.check_dev:
                _check_device(config)
                return 0

            steps = input_parsing(input_path)
            if args.check_input:
                return 0

            output_name = args.output or datetime.now().strftime(
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
