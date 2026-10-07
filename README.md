# eLux @ UniBS - Battery Testing Laboratory

This project runs battery test profiles on a Keithley 2461 SourceMeter over a
raw TCP socket using native SCPI commands. A test is split into three explicit
phases: instrument setup, profile execution, and guaranteed safe shutdown.

The runner supports constant-current (`CURR`), constant-voltage (`VOLT`),
measurement-only (`MEAS`), and early-stop (`STOP`) steps. Measurements are
streamed to CSV after every sample so that already acquired data is retained if
the test is interrupted.

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

The supplied `config.example.ini` uses deliberately low example limits. They
are not universal safe values: review them against the battery, leads, fixture,
and required test procedure before connecting the output.

## Test profile

The input must be a UTF-8 CSV with exactly this header:

```csv
duration,mode,source,compliance,meas_lb,meas_up,epsilon,tcompliance
60.0,CURR,1.0,5.0,1.1,4.5,1.0e-4,3600
60.0,VOLT,4.2,1.0,0.0,1.2,1.0e-4,3600
60.0,MEAS,,,,,,
0,STOP,,,,,,
```

Column meanings:

- `duration`: step duration in seconds, or `-1` for compliance-driven `CURR`
  and `VOLT` steps. `MEAS` cannot use `-1` because it has no compliance
  termination condition.
- `mode`: `CURR`, `VOLT`, `MEAS`, or `STOP`.
- `source`: current in amperes for `CURR`; voltage in volts for `VOLT`.
- `compliance`: voltage limit for `CURR`; current limit for `VOLT`.
- `meas_lb`, `meas_up`: inclusive software bounds for measured voltage in
  `CURR` or measured current in `VOLT`. Leaving the range advances to the next
  step.
- `epsilon`: positive tolerance used by a `duration=-1` compliance step.
- `tcompliance`: maximum uninterrupted time in compliance. The timer resets if
  the instrument leaves compliance.

For `MEAS`, the source, compliance, bounds, epsilon, and compliance-time fields
are ignored; current and voltage are both acquired. For `STOP`, every field
except `mode` is ignored.

For negative-source tests, compliance termination compares magnitudes:
`abs(abs(measured_value) - applied_compliance) <= epsilon`.

## Usage

Start by copying the examples to the default names:

```bash
cp config.example.ini config.ini
cp steps.example.csv steps.csv
```

Edit `config.ini`, especially the device address and both global compliance
ceilings, then inspect `steps.csv` before connecting a battery.

Validate and summarize a profile without connecting to the instrument:

```bash
python main.py --check-input
```

Check connectivity and leave the instrument in the safe shutdown state:

```bash
python main.py --check-dev
```

Run a test with default file names (`config.ini` and `steps.csv`):

```bash
python main.py
```

Override paths or names from the command line:

```bash
python main.py \
  --config lab.ini \
  --in-dir ./profiles \
  --in-file cycle.csv \
  --out-dir ./results \
  --out-name cycle_01.csv
```

Command-line input and output directories take precedence over `config.ini`.
If `--out-name` is omitted, the output name is
`YYYYMMDDTHHMM_output.csv` in local system time.

## Output

The output CSV contains:

```text
timestamp,idphase,state,current,voltage
```

- `timestamp`: Unix timestamp with millisecond precision
- `idphase`: one-based CSV step number
- `state`: `CURR`, `VOLT`, `VLIM`, `ILIM`, or `MEAS`
- `current`: measured/source-readback current in amperes
- `voltage`: measured/source-readback voltage in volts

## MATLAB visualization

Open `plot_measurements.m` and set `fnInput` to the test-profile CSV and
`fnMeasures` to the measurement CSV. Running the script creates two workspace
tables named `tblTest` and `tblMeasures`, then plots current and voltage in
synchronized subplots. Time is expressed in seconds from the first measurement,
which is assigned `t = 0`.

A second figure shows the programmed test profile. `CURR` and `VOLT` source
levels use separate Y axes, while `MEAS` phases occupy time without drawing a
source trace. The profile ends at the first `STOP` row. Because this figure uses
programmed rather than measured durations, the script reports an error if a
phase before `STOP` has `duration = -1`.

## Python visualization

Install Matplotlib with:

```bash
python -m pip install -r requirements.txt
```

Display the programmed profile and acquired measurements with:

```bash
python plot.py \
  --file-step steps.example.csv \
  --file-measures output/measurement.csv
```

The first figure shows the programmed `CURR` and `VOLT` levels against time on
separate Y axes. `MEAS` steps contribute to elapsed time but are not drawn;
the first `STOP` ends the profile, and steps whose duration is `-1` are ignored
and do not contribute to the plotted timeline. The second figure shows measured
current and voltage on separate Y axes. Both figures express elapsed time in
hours, starting from `t = 0`. In the profile, each `MEAS` step appears as an
empty interval whose width corresponds to its configured duration.

Without `--output`, both figures are displayed interactively on screen. Use
`--output` without a destination to save both plots in a single PNG image
instead:

```bash
python plot_results.py \
  --file-step steps.example.csv \
  --file-measures output/cycle_01.csv \
  --output
```

The image is written to the current directory using the measurement filename
with a `.png` extension. In this example, the output is `./cycle_01.png`.

Pass an explicit image path to select a different destination or format:

```bash
python plot.py \
  --file-step steps.example.csv \
  --file-measures output/cycle_01.csv \
  --output figures/cycle_summary.png
```

When `--output` is present, the program saves the image without opening the
interactive plot windows.

