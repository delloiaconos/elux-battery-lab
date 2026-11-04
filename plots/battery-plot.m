%% Keithley 2461 profile and measurement viewer
% Paths are relative to MATLAB's Current Folder (examples assume plots/).
% Set either filename to "" to display only the other dataset.
fnInput = "../battery-cycler/examples/steps.example.csv";
fnMeasures = "../output/measurements.csv";

hasSteps = strlength(fnInput) > 0;
hasMeasures = strlength(fnMeasures) > 0;
if ~hasSteps && ~hasMeasures
    error("KeithleyPlot:MissingInput", "Provide a profile or measurement file.");
end

% Keep the original CSV columns, including sw_compliance, in the workspace.
tblTest = table();
tblMeasures = table();
segments = zeros(0, 4); % start seconds, end seconds, mode (1=CURR, 2=VOLT, 3=MEAS), source
elapsed = 0;

%% Load and validate the programmed profile
if hasSteps
    tblTest = readCsv(fnInput, ["duration", "mode", "source"]);
    modes = upper(strtrim(string(tblTest.mode)));
    durations = numericColumn(tblTest.duration);
    sources = numericColumn(tblTest.source);
    for row = 1:height(tblTest)
        mode = modes(row);
        if mode == "STOP"
            break;
        end
        if ismissing(mode) || ~ismember(mode, ["CURR", "VOLT", "MEAS"])
            error("KeithleyPlot:InvalidMode", "Unsupported mode at CSV row %d.", row + 1);
        end
        duration = durations(row);
        if ~isfinite(duration) || (duration < 0 && duration ~= -1)
            error("KeithleyPlot:InvalidDuration", ...
                "Duration must be finite and >= 0 or -1 at CSV row %d.", row + 1);
        end
        if duration == -1
            continue; % Like battery-plot.py: omit indefinite phases and their time.
        end
        source = NaN;
        if mode == "CURR" || mode == "VOLT"
            source = sources(row);
            if ~isfinite(source)
                error("KeithleyPlot:InvalidSource", ...
                    "Source must be finite at CSV row %d.", row + 1);
            end
        end
        modeId = find(["CURR", "VOLT", "MEAS"] == mode);
        segments(end + 1, :) = [elapsed, elapsed + duration, modeId, source]; %#ok<SAGROW>
        elapsed = elapsed + duration;
    end
    if isempty(segments)
        error("KeithleyPlot:EmptyProfile", "No finite test steps to plot.");
    end
end

%% Load and validate measurements before opening figures
if hasMeasures
    tblMeasures = readCsv(fnMeasures, ["timestamp", "current", "voltage"]);
    if height(tblMeasures) == 0
        error("KeithleyPlot:EmptyMeasureFile", "The measurement file contains no samples.");
    end
    timestamp = numericColumn(tblMeasures.timestamp);
    current = numericColumn(tblMeasures.current);
    voltage = numericColumn(tblMeasures.voltage);
    if any(~isfinite(timestamp)) || any(~isfinite(current)) || any(~isfinite(voltage))
        error("KeithleyPlot:InvalidMeasurement", "Measurements must be finite numeric values.");
    end
    if any(diff(timestamp) < 0)
        error("KeithleyPlot:NonMonotonicTime", "Measurement timestamps must not decrease.");
    end
    timeHours = (timestamp - timestamp(1)) / 3600;
end

%% Figure 1: programmed steps, current on left and voltage on right
if hasSteps
    figProfile = figure("Name", "Test profile", "Color", "white");
    axProfile = axes("Parent", figProfile);
    yyaxis(axProfile, "left");
    hold(axProfile, "on");
    for k = 1:size(segments, 1)
        if segments(k, 3) == 1
            plot(axProfile, segments(k, 1:2) / 3600, repmat(segments(k, 4), 1, 2), ...
                "Color", [0.00, 0.45, 0.74], "LineWidth", 2);
        end
    end
    ylabel(axProfile, "Current [A]");
    yyaxis(axProfile, "right");
    hold(axProfile, "on");
    for k = 1:size(segments, 1)
        if segments(k, 3) == 2
            plot(axProfile, segments(k, 1:2) / 3600, repmat(segments(k, 4), 1, 2), ...
                "Color", [0.85, 0.33, 0.10], "LineWidth", 2);
        end
    end
    ylabel(axProfile, "Voltage [V]");
    xlabel(axProfile, "Time [h]");
    title(axProfile, "Test profile");
    grid(axProfile, "on");
    profileEnd = elapsed / 3600;
    if profileEnd <= 0
        profileEnd = 1;
    end
    xlim(axProfile, [0, profileEnd]);
    fprintf("Loaded %d test steps into tblTest.\n", height(tblTest));
end

%% Figure 2: measured current and voltage on separate Y axes
if hasMeasures
    figMeasures = figure("Name", "Measurements", "Color", "white");
    axMeasures = axes("Parent", figMeasures);
    yyaxis(axMeasures, "left");
    plot(axMeasures, timeHours, current, "Color", [0.00, 0.45, 0.74], "LineWidth", 1.2);
    ylabel(axMeasures, "Current [A]");
    yyaxis(axMeasures, "right");
    plot(axMeasures, timeHours, voltage, "Color", [0.85, 0.33, 0.10], "LineWidth", 1.2);
    ylabel(axMeasures, "Voltage [V]");
    xlabel(axMeasures, "Time [h]");
    title(axMeasures, "Measured current and voltage");
    grid(axMeasures, "on");
    measurementEnd = max(timeHours);
    if measurementEnd <= 0
        measurementEnd = 1;
    end
    xlim(axMeasures, [0, measurementEnd]);
    fprintf("Loaded %d measurements into tblMeasures.\n", height(tblMeasures));
end

%% Local helpers
function tbl = readCsv(filename, requiredColumns)
    if ~isfile(filename)
        error("KeithleyPlot:FileNotFound", "CSV file not found: %s", filename);
    end
    tbl = readtable(filename, "VariableNamingRule", "preserve");
    missing = setdiff(requiredColumns, string(tbl.Properties.VariableNames));
    if ~isempty(missing)
        error("KeithleyPlot:MissingColumns", "Missing column(s) in %s: %s", ...
            filename, strjoin(missing, ", "));
    end
end

function values = numericColumn(values)
    if ~isnumeric(values)
        values = str2double(string(values));
    end
end
