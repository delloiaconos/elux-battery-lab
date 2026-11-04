# Battery profile and measurement plots

These scripts visualize CSV files produced by the
[battery cycler](../battery-cycler/README.md). They read files locally and do not
connect to the instrument.

| Script | Displays | Time axis |
| --- | --- | --- |
| [plot.py](plot.py) | Programmed profile and measured current/voltage | Hours |
| [plot.m](plot.m) | Measured current and voltage in synchronized subplots; loads the profile into a table | Seconds |

## Python

Use Python 3.10 or newer. Install the plotting dependencies from the repository
root:

```bash
python -m pip install -r plots/requirements.txt
```

The examples below also run from the repository root. Replace
`output/measurement.csv` with an existing measurement file.

### Interactive display

```bash
python plots/plot.py \
  --file-step battery-cycler/examples/steps.example.csv \
  --file-measures output/measurement.csv
```

When both files are supplied, two windows open: the programmed profile and the measurements. Each uses
separate Y axes for current in amperes and voltage in volts. An interactive
Matplotlib backend and graphical display are required.

Supply only one input to show just that plot:

```bash
python plots/plot.py --file-step battery-cycler/examples/steps.example.csv
python plots/plot.py --file-measures output/measurement.csv
```

At least one input is required. Each supplied file is validated; errors in one
file are not ignored when both are supplied.

### Save an image

Save the supplied plot, or both plots together, without opening interactive windows:

```bash
python plots/plot.py \
  --file-step battery-cycler/examples/steps.example.csv \
  --file-measures output/measurement.csv \
  --output figures/cycle.png
```

For a machine without a graphical display, select the noninteractive backend:

```bash
MPLBACKEND=Agg python plots/plot.py \
  --file-step battery-cycler/examples/steps.example.csv \
  --file-measures output/measurement.csv \
  --output figures/cycle.png
```

| Option | Behavior |
| --- | --- |
| `--file-step PATH` | Optional profile CSV; required if measurements are omitted |
| `--file-measures PATH` | Optional measurement CSV; required if profile is omitted |
| `--output` | Save using the measurement basename (profile basename for steps only) with `.png` in the working directory |
| `--output PATH` | Save to the given file, or into an existing directory using the measurement basename (profile basename for steps only) |
| `-h`, `--help` | Show command-line help |

Relative paths resolve from the working directory. Missing parent directories
are created for output files. A filename without an extension gets `.png`;
other extensions select formats supported by Matplotlib, such as PDF or SVG.
An existing output file is overwritten. An output path intended as a directory
must already exist; otherwise it is treated as a filename. Saved figures use a
12 × 9 inch layout for both plots or 12 × 4.5 inches for one plot, at 150 dpi, and the absolute output path is printed.

### Profile and measurement behavior

The profile plot shows the programmed source values, not a reconstruction of
the actual run:

- `CURR` draws a current segment; `VOLT` draws a voltage segment.
- `MEAS` contributes time but leaves a gap in the source traces.
- The first `STOP` ends the plotted profile.
- `duration=-1` phases are skipped entirely, including their time.
- At least one finite phase is required; other negative durations are rejected.

The measurement axis starts at the first sample, independently of the profile
axis. Early termination and `CSWL`/`VSWL` transitions can make the measured run
longer or shorter than the programmed timeline. The plots do not mark phase
IDs, hardware trips, software-limit states, or compliance thresholds.

## MATLAB

Open [plot.m](plot.m) and edit its first two assignments. For example, with
MATLAB's Current Folder set to `plots/`:

```matlab
fnInput = "../battery-cycler/examples/steps.example.csv";
fnMeasures = "../output/measurement.csv";
```

Run the script from the editor. Paths resolve from MATLAB's current working
folder; use absolute paths if running from another location. The assignments
in the script overwrite any earlier workspace values for these variables.

The script creates:

- `tblTest`: the input profile table.
- `tblMeasures`: the measurement table.
- One figure with current and voltage in separate subplots sharing the X axis.

Time is in seconds relative to the first measurement. The current script loads
but does not plot or simulate the profile, so it does not reject indefinite
profile durations. It has no command-line output option or automatic export;
use MATLAB's figure export controls to save the figure. A MATLAB version
supporting `tiledlayout` and `readtable` with `VariableNamingRule` is required.

## CSV requirements

Both scripts accept extra columns, including the profile's `sw_compliance`.
The full profile specification is in the
[battery-cycler guide](../battery-cycler/README.md#test-profile).

| Input | Python required columns | MATLAB required columns |
| --- | --- | --- |
| Profile | `duration,mode,source` | `duration,mode,source,compliance,meas_lb,meas_up,compliance_lim,compliance_t` |
| Measurements | `timestamp,current,voltage` | `timestamp,idphase,state,current,voltage` |

Measurement timestamps are Unix seconds; current is in amperes and voltage in
volts. Both scripts require at least one measurement and finite numeric
measurement values. Python accepts UTF-8 with or without a BOM, skips empty
rows, and rejects decreasing timestamps. MATLAB warns about decreasing
timestamps but still plots the samples. Equal adjacent timestamps are allowed.

Neither script replaces the runner's profile validation. Before a hardware
run, use the runner's `--check-input` option.

## Troubleshooting

- Missing `matplotlib`: install `plots/requirements.txt` with the same Python
  interpreter used to launch the script.
- No display available: use `MPLBACKEND=Agg` together with `--output`.
- Missing file: check the working directory and both input paths.
- Missing columns: supply the original profile and runner measurement CSV,
  not the JSON stream printed to stdout.
- No finite test steps: Python needs at least one finite phase before `STOP`.
- Invalid measurements: inspect the CSV for blank, nonnumeric, or non-finite
  values; neither script repairs them.

Return to the [project overview](../README.md).
