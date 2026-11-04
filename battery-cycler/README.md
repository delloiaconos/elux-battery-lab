# Keithley 2461 Battery Test Runner

This script runs battery test profiles on a Keithley 2461 SourceMeter over a
raw TCP socket using native SCPI commands. A test is split into three explicit
phases: instrument setup, profile execution, and best-effort shutdown.

The runner supports constant-current (`CURR`), constant-voltage (`VOLT`),
measurement-only (`MEAS`), and early-stop (`STOP`) steps. Measurements are
streamed to CSV after every sample so that already acquired data is retained if
the test is interrupted.

See the [repository overview](../README.md) for the other lab tools and plotting.

## Requirements

- Python 3.10 or newer
- A Keithley 2461 configured for the native SCPI command set
- TCP access to the instrument's raw socket (normally port 5025)

There are no third-party Python dependencies. `requirements.txt` is included
for completeness.

> **Safety:** Battery testing can involve hazardous energy. Verify wiring,
> polarity, ranges, compliance limits, thermal protection, and emergency-stop
> procedures before enabling the output. Validate the standard SCPI sequences
> on the exact instrument and firmware used in the lab.

## Project structure

```text
battery-cycler/
├── main.py                     # Arguments, signals, and orchestration
├── battery_cycler/
│   ├── __init__.py
│   ├── __main__.py             # python -m battery_cycler
│   ├── config.py               # INI configuration loading and validation
│   ├── core/
│   │   ├── __init__.py
│   │   ├── models.py           # Models, constants, and exceptions
│   │   └── runner.py           # Phase execution and measurement CSV output
│   ├── instruments/
│   │   ├── __init__.py
│   │   └── keithley2461.py     # TCP/SCPI transport and instrument operations
│   └── profiles/
│       ├── __init__.py
│       └── parser.py          # Profile CSV parsing and validation
├── examples/
│   ├── config.example.ini
│   └── steps.example.csv
├── tests/                      # Simulated instrument and profile tests
├── output/                     # Locally generated measurement files
├── requirements.txt
└── README.md
```

Run the commands below from `battery-cycler/`. Both `python main.py` and
`python -m battery_cycler` launch the same CLI, without installing the package.
Relative configuration, input, and output paths resolve from the working
directory. The repository-level `battery-cycler.sh` continues to use `main.py`.
Plotting utilities live in the repository's separate `plots/` directory.

## Configuration

Create `config.ini` in the working directory. The human-readable INI file uses
Python's standard `[DEFAULT]` section:

```ini
[DEFAULT]
dev-address = 192.168.100.10
dev-port = 5025
in-dir = .
out-dir = ./output
sampling-time = 1.0
voltage-compliance = 7.0
current-compliance = 7.0
```

`voltage-compliance` is the maximum voltage limit applied while sourcing
current. `current-compliance` is the maximum current limit applied while
sourcing voltage. The applied limit for each source step is the lower of the
profile value and the matching configuration maximum.

The supplied `examples/config.example.ini` uses deliberately low example limits. They
are not universal safe values: review them against the battery, leads, fixture,
and required test procedure before connecting the output.

## Test profile

Profiles are UTF-8 CSV files with the following header in this order:

```csv
duration,mode,source,compliance,meas_lb,meas_up,compliance_lim,compliance_t,sw_compliance
5,MEAS,,,,,,,
30,CURR,0.1,4.2,2.5,4.25,0.01,10,0.2
15,VOLT,4.0,0.2,-0.2,0.2,0.001,10,4.2
0,STOP,,,,,,,
```

The legacy header with the first eight columns (without `sw_compliance`) is
also accepted. `CSWL` and `VSWL` are runtime states, not valid input modes.

| Column | Meaning |
| --- | --- |
| `duration` | Seconds in the initial mode; nonnegative, or exactly `-1` for no duration deadline |
| `mode` | `CURR`, `VOLT`, `MEAS`, or `STOP` |
| `source` | Signed current in A for `CURR`, signed voltage in V for `VOLT` |
| `compliance` | Positive hardware voltage limit in `CURR`, current limit in `VOLT` |
| `meas_lb`, `meas_up` | Signed lower/upper bounds on voltage in `CURR`, current in `VOLT`; crossing a bound enters a software-limit state |
| `compliance_lim` | Positive magnitude threshold that terminates a phase; see the state table below |
| `compliance_t` | Nonnegative time limit in seconds: continuous hardware tripping, or elapsed time since entering a software-limit state |
| `sw_compliance` | Optional positive hardware compliance after switching: V in `CSWL`, A in `VSWL` |

All numeric values must be finite. `CURR` and `VOLT` require all fields except
`sw_compliance`; `meas_lb` must not exceed `meas_up`. `MEAS` requires only a
valid duration and ignores the source and limit fields. `STOP` ignores all
other fields and ends execution before taking a sample.

`duration=-1` disables the initial duration deadline. In `CURR` and `VOLT`,
software-limit transitions remain enabled, but the current implementation does
not apply hardware-trip termination to these indefinite phases. `MEAS` also
accepts `-1` and then runs until interrupted; use a finite duration if later
steps must be reached.

## Hardware compliance and phase termination

Hardware compliance restricts the source output; a termination threshold tells
the program when to advance to the next phase. They are separate settings.
The applied hardware compliance is the lower of the requested profile value
and the matching global ceiling from the INI file.

| Runtime state | Condition for threshold termination | Timer |
| --- | --- | --- |
| `VLIM` (initial `CURR`) | `abs(current) < compliance_lim` | Continuous time in hardware compliance |
| `ILIM` (initial `VOLT`) | `abs(voltage) < compliance_lim` | Continuous time in hardware compliance |
| `CSWL` | `abs(voltage) < compliance_lim` | Time since switching to current sourcing |
| `VSWL` | `abs(current) < compliance_lim` | Time since switching to voltage sourcing |

For initial `CURR`/`VOLT` phases with nonnegative duration, threshold and timer
termination apply only while the instrument reports a hardware trip. The timer
resets when the trip clears. Reaching `compliance_t` ends the phase; zero ends
it on the first applicable sample. Hardware-trip termination is evaluated
before a software-limit transition for the same sample.

## Software limits

The extended CSV header is:

```csv
duration,mode,source,compliance,meas_lb,meas_up,compliance_lim,compliance_t,sw_compliance
```

`compliance` sets the hardware limit in the initial source mode;
`sw_compliance` sets it after the software-limit transition. Both must be
positive when supplied. `compliance_lim` is only a termination threshold,
not a hardware limit. `MEAS` and `STOP` ignore `sw_compliance`.

In `VOLT`, current strictly above `meas_up` or below `meas_lb` switches the
instrument to current sourcing at the crossed bound and enters `CSWL`.
In `CURR`, the dual behavior switches to voltage sourcing at the crossed
voltage bound and enters `VSWL`. Equality with a bound does not switch modes.
The new hardware compliance comes from `sw_compliance`: volts in `CSWL`,
amperes in `VSWL`. It is independent of the original `source` and of the
termination threshold `compliance_lim`. The corresponding global compliance
ceiling still caps the applied value. When `sw_compliance` is empty or the
legacy eight-column header is used, the corresponding global compliance is
used (not `abs(source)`). This changes the fallback behavior of older profiles.

For example, a discharge profile can use a 4.3 V hardware compliance in `CSWL`, while
the phase ends when the measured voltage magnitude drops below 3.6 V. A
`VSWL` phase can use a 0.5 A hardware compliance and a 0.4 A current cutoff.

The software-limit state lasts until `abs(voltage) < compliance_lim` in `CSWL`,
or `abs(current) < compliance_lim` in `VSWL`, or until `compliance_t` seconds
have elapsed since the switch. The original `duration` no longer ends a step
once it has entered a software-limit state. These transitions also apply to
steps with `duration = -1`. There is no automatic switch back within a step.
CSV and JSON samples acquired after the switch report `CSWL` or `VSWL`.

Before a software-limit transition, hardware tripping retains its existing
cutoffs and continuous-compliance timer, including its reset when tripping
clears. Hardware trip termination takes priority if both conditions occur in
the same sample. As before, that hardware-trip termination logic applies to
steps with nonnegative duration.

## Usage

All commands in this guide assume the working directory is `battery-cycler/`.

### Prepare and validate a profile


Start by copying the examples to the default names:

```bash
cp examples/config.example.ini config.ini
cp examples/steps.example.csv steps.csv
```

Edit `config.ini`, especially the device address and both global compliance
ceilings, then inspect `steps.csv` before connecting a battery.

Validate and summarize a profile without connecting to the instrument:

```bash
python main.py --check-input
```

### Check, run, and reset

Check connectivity and leave the instrument in the safe shutdown state:

```bash
python main.py --check-dev
```

Run a test with default file names (`config.ini` and `steps.csv`):

```bash
python main.py
```

To keep a test running in a detachable terminal session, start GNU Screen from
the project directory and launch the program inside it:

```bash
screen -S battery-test
python main.py
```

Detach while leaving the program running with `Ctrl+A`, then `D`. To find and
recover the session later, for example after reconnecting over SSH, run:

```bash
screen -ls
screen -r battery-test
```

If the session is still attached to another terminal, detach it there and
attach here with:

```bash
screen -d -r battery-test
```

Override paths or names from the command line:

```bash
python main.py \
  --config lab.ini \
  --in-dir ./profiles \
  --input cycle.csv \
  --out-dir ./results \
  --output cycle_01.csv
```

Command-line input and output directories take precedence over `config.ini`.
If `--output` is omitted, the output name is
`YYYYMMDDTHHMM_output.csv` in local system time.

Reset the instrument without loading a profile or starting a test:

```bash
python main.py --config config.ini --reset
```

This identifies the instrument, sends `:ABORt` followed by `*RST`, waits for
`*OPC?`, then leaves the output off in high-impedance mode and closes the
connection. The configured INI file is required; an input CSV is not.
`--reset`, `--check-input`, and `--check-dev` are mutually exclusive.

### Command-line reference

| Option | Default / effect |
| --- | --- |
| `--config PATH` | `config.ini`; load the full INI configuration |
| `--input PATH` | `steps.csv`; relative to the selected input directory |
| `--in-dir PATH` | Override the INI input directory |
| `--output PATH` | Output filename; default `YYYYMMDDTHHMM_output.csv` |
| `--out-dir PATH` | Override the INI output directory |
| `--check-input` | Validate and summarize the profile without connecting |
| `--check-dev` | Reset, configure, verify buffers/four-wire sensing, then shut down |
| `--reset` | Send `:ABORt` and `*RST`, then shut down without loading a profile |
| `-h`, `--help` | Show help without loading configuration |

Relative paths resolve from the process working directory, not the INI file's
location. Relative `--input` and `--output` paths are joined to their respective
directories; absolute paths bypass those directories. Output directories are
created automatically. Existing output files with the same name are overwritten.

All operations except help require a complete, valid configuration.
`--check-dev` and `--reset` operate on the hardware and do not require a CSV.
Reset-only mode skips buffer verification and four-wire setup.

Exit codes are `0` for success, `1` for instrument or OS errors, `2` for invalid
configuration/profile/arguments, `130` for Ctrl+C, and `128 + signal number`
for handled termination signals.

### Optional shell launcher

The repository's [battery-cycler.sh](../battery-cycler.sh) starts the runner
inside GNU Screen and activates the repository-root `.env/` virtual environment.
It takes three positional arguments: configuration file, input CSV, output CSV.
Use absolute paths to avoid ambiguity with the INI input/output directories:

```bash
bash ../battery-cycler.sh /path/to/config.ini /path/to/steps.csv /path/to/result.csv
```

The Screen session uses the output filename without its extension as its name.
Detach with `Ctrl+A`, then `D`; reattach with `screen -r SESSION_NAME`.
The launcher currently runs Python directly; its MQTT variables do not enable
publishing. Use the Python CLI directly for reset and validation options.

## Output

The output CSV contains:

```text
timestamp,idphase,state,current,voltage
```

- `timestamp`: Unix timestamp with millisecond precision
- `idphase`: one-based CSV step number
- `state`: `CURR`, `VOLT`, `VLIM`, `ILIM`, `CSWL`, `VSWL`, or `MEAS`
- `current`: measured/source-readback current in amperes
- `voltage`: measured/source-readback voltage in volts

Standard output contains one JSON object per measurement (NDJSON), for example:

```json
{"time":1.234,"timestamp":1791800000.123,"idphase":1,"state":"CURR","current":0.1,"voltage":3.7}
```

The object includes elapsed seconds from the start of the run, a Unix timestamp,
the one-based phase number, measurement state, current, and voltage. Status,
progress, and error messages are written to standard error so standard output
can be consumed as a stream of JSON records.

## Shutdown behavior

Normal completion, `STOP`, communication errors, `Ctrl+C`, Linux `SIGTERM`, and
Linux `SIGHUP` all pass through shutdown. The signal handlers convert the first
termination request into a controlled interruption; additional termination
requests are ignored while the safety sequence is running. An unavoidable
`SIGKILL` cannot be handled by any process.

The program attempts every shutdown action even if an earlier action fails:
continuous triggering stopped, high-impedance output-off mode selected, output
switched off, `AUTO` stored as the next power-on trigger preference, and TCP
connection closed. It intentionally does not issue `TRIG:CONT RESTART`, because
that command would immediately start measurements while the output is off in
high-impedance mode.

## SCPI notes

Source-mode samples use source readback and the active sense function in one
`READ?` operation. Compliance state is read with the 2461 native
`...LIM:TRIP?` queries. In `MEAS`, the instrument sources `0 A`, applies the
configured global voltage compliance, enables source readback, and measures
voltage. The returned source readback and voltage are stored as current and
voltage with state `MEAS`.

The source function is queried before configuring each phase. When changing
between voltage and current sourcing (including `CSWL`, `VSWL`, and entry to
`MEAS`), output is explicitly switched off in high-impedance mode before the
function change. The new source level and compliance are configured before
output is enabled again. These transitions briefly disconnect the terminals;
updates that retain the same source function do not switch output off.
High-impedance output-off mode is selected again for the new function.

During setup, four-wire remote sensing is enabled and verified independently
for voltage and current with `SENS:VOLT:RSEN ON` and `SENS:CURR:RSEN ON`.
Active measurements therefore use the four-terminal configuration. When the
output is off in high-impedance mode, the instrument physically disconnects
the remote-sense lines; the configured four-wire mode is used again when the
output is enabled.

Startup also stops continuous triggering, switches the output off, clears both
default reading buffers with `TRAC:CLE "defbuffer1"` and
`TRAC:CLE "defbuffer2"`, and verifies with `TRAC:ACT?` that both buffers contain
zero readings before the test can start.

The command choices follow the
[Keithley 2461 Reference Manual](https://www.tek.com/en/keithley-source-measure-units/smu-2450-60-graphical-sourcemeter-manual-3).

## Tests

Run the standard-library test suite from `battery-cycler/`:

```bash
python -m unittest discover -s tests -v
```

Tests use simulated instruments and clocks to cover profile parsing,
software-limit transitions, compliance settings, source switching, and reset
behavior. They do not connect to hardware or replace instrument validation.

For result visualization, see the [project plotting instructions](../README.md#visualizing-results).
