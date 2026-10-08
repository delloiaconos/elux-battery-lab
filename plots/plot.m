%% Keithley 2461 test and measurement viewer
% Set these two file names before running the script.
fnInput = "steps.example.csv";
fnMeasures = "output/measurements.csv";

%% Load the test profile and measurements into separate tables
if ~isfile(fnInput)
    error("KeithleyPlot:InputNotFound", ...
        "Test input file not found: %s", fnInput);
end

if ~isfile(fnMeasures)
    error("KeithleyPlot:MeasuresNotFound", ...
        "Measurement file not found: %s", fnMeasures);
end

tblTest = readtable(fnInput, "VariableNamingRule", "preserve");
tblMeasures = readtable(fnMeasures, "VariableNamingRule", "preserve");

requiredTestColumns = [ ...
    "duration", "mode", "source", "compliance", ...
    "meas_lb", "meas_up", "epsilon", "tcompliance"];
requiredMeasureColumns = [ ...
    "timestamp", "idphase", "state", "current", "voltage"];

missingTestColumns = setdiff( ...
    requiredTestColumns, string(tblTest.Properties.VariableNames));
if ~isempty(missingTestColumns)
    error("KeithleyPlot:InvalidTestFile", ...
        "Missing test column(s): %s", strjoin(missingTestColumns, ", "));
end

missingMeasureColumns = setdiff( ...
    requiredMeasureColumns, string(tblMeasures.Properties.VariableNames));
if ~isempty(missingMeasureColumns)
    error("KeithleyPlot:InvalidMeasureFile", ...
        "Missing measurement column(s): %s", ...
        strjoin(missingMeasureColumns, ", "));
end

if height(tblMeasures) == 0
    error("KeithleyPlot:EmptyMeasureFile", ...
        "The measurement file contains no samples.");
end

%% Convert measurement columns and build a relative time axis
timestamp = tblMeasures.timestamp;
current = tblMeasures.current;
voltage = tblMeasures.voltage;

if ~isnumeric(timestamp)
    timestamp = str2double(string(timestamp));
end
if ~isnumeric(current)
    current = str2double(string(current));
end
if ~isnumeric(voltage)
    voltage = str2double(string(voltage));
end

if any(~isfinite(timestamp))
    error("KeithleyPlot:InvalidTimestamp", ...
        "The timestamp column contains invalid values.");
end
if any(~isfinite(current)) || any(~isfinite(voltage))
    error("KeithleyPlot:InvalidMeasurement", ...
        "The current or voltage column contains invalid values.");
end

timeSeconds = timestamp - timestamp(1);
if any(diff(timeSeconds) < 0)
    warning("KeithleyPlot:NonMonotonicTime", ...
        "Measurement timestamps are not monotonically increasing.");
end

%% Plot current and voltage in synchronized subplots
fig = figure( ...
    "Name", "Keithley 2461 measurements", ...
    "Color", "white");
layout = tiledlayout(fig, 2, 1, ...
    "TileSpacing", "compact", ...
    "Padding", "compact");

axCurrent = nexttile(layout);
plot(axCurrent, timeSeconds, current, ...
    "LineWidth", 1.2, ...
    "Color", [0.00, 0.45, 0.74]);
grid(axCurrent, "on");
ylabel(axCurrent, "Current [A]");
title(axCurrent, "Current");

axVoltage = nexttile(layout);
plot(axVoltage, timeSeconds, voltage, ...
    "LineWidth", 1.2, ...
    "Color", [0.85, 0.33, 0.10]);
grid(axVoltage, "on");
xlabel(axVoltage, "Time from first sample [s]");
ylabel(axVoltage, "Voltage [V]");
title(axVoltage, "Voltage");

title(layout, "Keithley 2461 battery-test measurements");
linkaxes([axCurrent, axVoltage], "x");

timeMaximum = max(timeSeconds);
if timeMaximum > 0
    xlim(axCurrent, [0, timeMaximum]);
end

fprintf("Loaded %d test steps into tblTest.\n", height(tblTest));
fprintf("Loaded %d measurements into tblMeasures.\n", height(tblMeasures));
