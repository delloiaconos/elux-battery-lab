# Battery profile and measurement plots

These scripts visualize CSV files produced by the
[battery cycler](../battery-cycler/README.md). They read files locally and do not
connect to the instrument.

| Script | Displays | Time axis |
| --- | --- | --- |
| [battery-plot.py](battery-plot.py) | Programmed profile and measured current/voltage | Hours |
| [battery-plot.m](battery-plot.m) | Programmed profile and measured current/voltage in separate figures | Hours |

## Python

Use Python 3.10 or newer. Install the plotting dependencies from the repository
root:

```bash
python -m pip install -r plots/requirements.txt
```

The examples below also run from the repository root. Replace
`output/measurement.csv` with an existing measurement file.

### Save with the default name

```bash
python plots/battery-plot.py \
  --steps battery-cycler/examples/steps.example.csv \
  --measures output/measurement.csv
```

The command saves `output.png` in the working directory. With both inputs,
the image contains the programmed profile and the measurements, each with
separate Y axes for current in amperes and voltage in volts. Without `--output`,
interactive windows also open (one per supplied dataset). Add `-q` or `--quiet`
to save `output.png` without opening windows:

```bash
python plots/battery-plot.py --steps battery-cycler/examples/steps.example.csv --quiet
```

Quiet mode controls windows only; the saved-file message and errors remain visible.

Supply only one input to save just that plot:

```bash
python plots/battery-plot.py --steps battery-cycler/examples/steps.example.csv
python plots/battery-plot.py --measures output/measurement.csv
```

At least one input is required. Each supplied file is validated; errors in one
file are not ignored when both are supplied.

### Save an image

Save the supplied plot, or both plots together, without opening interactive windows:

```bash
python plots/battery-plot.py \
  --steps battery-cycler/examples/steps.example.csv \
  --measures output/measurement.csv \
  --output figures/cycle.png
```

For a machine without a graphical display, select the noninteractive backend:

```bash
MPLBACKEND=Agg python plots/battery-plot.py \
  --steps battery-cycler/examples/steps.example.csv \
  --measures output/measurement.csv \
  --output figures/cycle.png
```

| Option | Behavior |
| --- | --- |
| `--steps PATH` | Optional profile CSV; required if measurements are omitted |
| `--measures PATH` | Optional measurement CSV; required if profile is omitted |
| `--output PATH` | Output image file path; defaults to `output.png` in the working directory |
| `-q`, `--quiet` | Disable windows when `--output` is omitted; still save `output.png` |
| `-h`, `--help` | Show command-line help |

Relative paths resolve from the working directory. Missing parent directories
are created for output files. A filename without an extension gets `.png`;
other extensions select formats supported by Matplotlib, such as PDF or SVG.
An existing output file is overwritten. `--output` requires a filename, optionally with a directory path; a directory
alone is rejected. Supplying `--output` without a value is an argument error.
Saved figures use a
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

Open [battery-plot.m](battery-plot.m) and edit its first two assignments. For example, with
MATLAB's Current Folder set to `plots/`:

```matlab
fnInput = "../battery-cycler/examples/steps.example.csv";
fnMeasures = "../output/measurement.csv";
```

Run the script from the editor or by filename:

```matlab
run('battery-plot.m')
```

Use `run` rather than typing `battery-plot` as a command, because the filename
contains a hyphen. Paths resolve from MATLAB's current working
folder; use absolute paths if running from another location. The assignments
in the script overwrite any earlier workspace values for these variables.

Set `fnInput = ""` for measurements only, or `fnMeasures = ""` for steps only.
At least one filename must be supplied. Both files are validated before figures
are created when both are supplied.

The script creates `tblTest` and `tblMeasures` in the workspace, retaining all
input columns, including `sw_compliance`. The table for an omitted file is empty.
Each supplied dataset gets its own figure, matching Python's interactive layout:
current on the left Y axis, voltage on the right, and elapsed time in hours.
Measurement time starts at the first sample.

The profile supports the current nine-column format and legacy profiles.
`MEAS` phases leave gaps, the first `STOP` ends the profile, and `duration=-1`
phases are skipped without adding time. No compliance thresholds or runtime
`CSWL`/`VSWL` transitions are drawn. At least one finite phase is required for
a profile plot; blank source fields are allowed for `MEAS` and `STOP`.

Use MATLAB's figure export controls to save figures; the script does not
implement Python's output/quiet CLI options. A MATLAB version supporting
local functions in scripts, `yyaxis`, and `readtable` with `VariableNamingRule`
is required.

## CSV requirements

Both scripts accept extra columns, including the profile's `sw_compliance`.
The full profile specification is in the
[battery-cycler guide](../battery-cycler/README.md#test-profile).

| Input | Python required columns | MATLAB required columns |
| --- | --- | --- |
| Profile | `duration,mode,source` | `duration,mode,source` |
| Measurements | `timestamp,current,voltage` | `timestamp,current,voltage` |

Measurement timestamps are Unix seconds; current is in amperes and voltage in
volts. Both scripts require at least one measurement and finite numeric
measurement values. Python accepts UTF-8 with or without a BOM and skips empty rows. Both scripts
reject decreasing timestamps. Equal adjacent timestamps are allowed.

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
