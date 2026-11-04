# eLux @ UniBS — Battery Testing Laboratory

Tools for running battery cycling experiments with a Keithley 2461 SourceMeter
and visualizing the acquired measurements. Profiles describe current-source,
voltage-source, and measurement-only phases; the runner controls the instrument
over SCPI/TCP and records measurements to CSV and a JSON stream.

## Repository overview

| Component | Purpose |
| --- | --- |
| [battery-cycler/](battery-cycler/README.md) | Test runner, configuration and profile examples, and automated tests |
| [battery-cycler.sh](battery-cycler.sh) | Bash launcher for a detachable GNU Screen session |
| [plots/plot.py](plots/plot.py) | Python visualization of profiles and measurements |
| [plots/plot.m](plots/plot.m) | MATLAB visualization of profiles and measurements |
| `output/` | Local measurement results, when selected as the output directory |

Lab-specific INI configurations and CSV profiles may also be kept locally in
the repository. Output locations are configurable.

## Requirements

The battery runner requires Python 3.10 or newer and uses only the standard
library. Hardware runs require a Keithley 2461 using the native SCPI command
set and a reachable TCP socket, normally on port 5025.

Python plotting has separate dependencies in
[plots/requirements.txt](plots/requirements.txt); the MATLAB script requires
MATLAB. The optional shell launcher requires Bash, GNU Screen, and a Python
virtual environment at `.env/` in the repository root.

## Getting started

From the repository root, validate the supplied example without connecting to
an instrument:

```bash
python battery-cycler/main.py \
  --config battery-cycler/examples/config.example.ini \
  --in-dir battery-cycler/examples \
  --input steps.example.csv \
  --check-input
```

For hardware operation, prepare a configuration and profile for the battery and
fixture being tested. Follow the [battery-cycler guide](battery-cycler/README.md)
for setup, CLI options, compliance limits, software-limit transitions, reset,
and shutdown behavior.

The typical workflow is to validate a profile, run the experiment, then inspect
the measurement CSV alongside the programmed profile. Measurements are flushed
to CSV after each sample; status messages go to stderr and measurement JSON
goes to stdout.

## Visualizing results

The [plotting guide](plots/README.md) documents Python image generation and
export, MATLAB usage, CSV requirements, and troubleshooting. Python
shows both the programmed profile and measurements; MATLAB displays measured
current and voltage and loads the profile into a workspace table.

## Operating considerations

Review wiring, polarity, four-wire sense connections, compliance settings, and
emergency-stop arrangements before enabling the output. Example settings are
illustrative, not universal battery limits. The runner attempts shutdown on
completion and handled interruptions, but cannot guarantee shutdown after power
loss, a broken connection, or forced process termination.
