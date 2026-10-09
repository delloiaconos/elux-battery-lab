"""Keithley 2461 TCP/SCPI communication and instrument operations."""

from __future__ import annotations

import math
import socket
import sys

from models import (
    AppConfig,
    InstrumentError,
    Measurement,
    SOCKET_TIMEOUT_SECONDS,
    TestStep,
    require_step_value,
)


class ScpiClient:
    """Line-oriented SCPI client for the instrument raw TCP socket."""

    def __init__(self, address: str, port: int) -> None:
        self.address = address
        self.port = port
        self._socket: socket.socket | None = None
        self._reader = None

    def connect(self) -> None:
        try:
            self._socket = socket.create_connection(
                (self.address, self.port), timeout=SOCKET_TIMEOUT_SECONDS
            )
            self._socket.settimeout(SOCKET_TIMEOUT_SECONDS)
            self._reader = self._socket.makefile("r", encoding="ascii", newline="\n")
        except OSError as exc:
            self.close()
            raise InstrumentError(
                f"Unable to connect to {self.address}:{self.port}: {exc}"
            ) from exc

    def send(self, command: str) -> None:
        if self._socket is None:
            raise InstrumentError("SCPI socket is not connected")
        try:
            self._socket.sendall((command + "\n").encode("ascii"))
        except OSError as exc:
            raise InstrumentError(
                f"Failed to send SCPI command {command!r}: {exc}"
            ) from exc

    def query(self, command: str) -> str:
        if self._reader is None:
            raise InstrumentError("SCPI socket is not connected")
        self.send(command)
        try:
            response = self._reader.readline()
        except OSError as exc:
            raise InstrumentError(
                f"Failed to read response to {command!r}: {exc}"
            ) from exc
        if response == "":
            raise InstrumentError(f"Instrument closed the connection after {command!r}")
        return response.strip()

    def close(self) -> None:
        if self._reader is not None:
            try:
                self._reader.close()
            except OSError:
                pass
            self._reader = None
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None


def _parse_float_response(response: str, command: str) -> float:
    try:
        value = float(response.split(",", maxsplit=1)[0])
    except ValueError as exc:
        raise InstrumentError(
            f"Invalid numeric response to {command!r}: {response!r}"
        ) from exc
    if not math.isfinite(value):
        raise InstrumentError(f"Non-finite response to {command!r}: {response!r}")
    return value


def _parse_pair_response(response: str, command: str) -> tuple[float, float]:
    fields = response.split(",")
    if len(fields) != 2:
        raise InstrumentError(
            f"Expected two values from {command!r}, got {response!r}"
        )
    return (
        _parse_float_response(fields[0], command),
        _parse_float_response(fields[1], command),
    )


def _parse_scpi_bool(response: str, command: str) -> bool:
    normalized = response.strip().upper()
    if normalized in {"1", "ON", "TRUE"}:
        return True
    if normalized in {"0", "OFF", "FALSE"}:
        return False
    raise InstrumentError(f"Invalid Boolean response to {command!r}: {response!r}")


def setup(config: AppConfig) -> ScpiClient:
    """Connect, identify, reset, and configure safe four-wire operation."""
    client = ScpiClient(config.dev_address, config.dev_port)
    print(f"Connecting to Keithley 2461 at {config.dev_address}:{config.dev_port}...")
    connected = False
    try:
        client.connect()
        connected = True
        identification = client.query("*IDN?")
        idn_upper = identification.upper()
        if "KEITHLEY" not in idn_upper or "MODEL 2461" not in idn_upper:
            raise InstrumentError(
                "Unexpected instrument identity: "
                f"{identification!r}; expected a Keithley 2461"
            )
        print(f"Instrument: {identification}")

        client.send("*RST")
        if client.query("*OPC?") != "1":
            raise InstrumentError("Instrument did not acknowledge reset completion")
        client.send(":TRIG:CONT OFF")
        client.send(":OUTP:SMOD HIMP")
        client.send(":OUTP OFF")

        client.send(":SENS:VOLT:RSEN ON")
        client.send(":SENS:CURR:RSEN ON")
        for query in (":SENS:VOLT:RSEN?", ":SENS:CURR:RSEN?"):
            if not _parse_scpi_bool(client.query(query), query):
                raise InstrumentError(
                    f"Instrument did not enable four-wire sensing ({query})"
                )
        return client
    except BaseException:
        if connected:
            try:
                shutdown(client)
            except Exception as shutdown_error:
                print(
                    f"ERROR during setup shutdown: {shutdown_error}",
                    file=sys.stderr,
                )
        else:
            client.close()
        raise


def shutdown(client: ScpiClient | None) -> None:
    """Best-effort safe shutdown; all commands are attempted before closing TCP."""
    if client is None:
        return

    errors: list[str] = []
    for command in (
        ":TRIG:CONT OFF",
        ":OUTP:SMOD HIMP",
        ":OUTP OFF",
        ":TRIG:CONT AUTO",
    ):
        try:
            client.send(command)
        except Exception as exc:  # Continue so later safety actions are still attempted.
            errors.append(f"{command}: {exc}")
    client.close()
    print(
        "Instrument triggering stopped, output set to high impedance and "
        "switched off; TCP closed."
    )
    if errors:
        raise InstrumentError("Shutdown was incomplete: " + "; ".join(errors))


def configure_step(
    client: ScpiClient, config: AppConfig, step: TestStep
) -> float | None:
    """Configure one executable test phase and enable the output."""
    client.send(":OUTP:SMOD HIMP")
    client.send(":OUTP OFF")

    if step.mode == "MEAS":
        client.send(":SOUR:FUNC CURR")
        client.send(":SOUR:CURR:RANG:AUTO ON")
        client.send(f":SOUR:CURR:VLIM {config.voltage_compliance:.12g}")
        client.send(":SOUR:CURR:READ:BACK ON")
        client.send(':SENS:FUNC "VOLT"')
        client.send(":SENS:VOLT:RANG:AUTO ON")
        client.send(":SOUR:CURR 0")
        client.send(":OUTP ON")
        return None

    source = require_step_value(step, "source")
    requested_compliance = require_step_value(step, "compliance")

    if step.mode == "CURR":
        applied_compliance = min(requested_compliance, config.voltage_compliance)
        client.send(":SOUR:FUNC CURR")
        client.send(":SOUR:CURR:RANG:AUTO ON")
        client.send(f":SOUR:CURR:VLIM {applied_compliance:.12g}")
        client.send(":SOUR:CURR:READ:BACK ON")
        client.send(':SENS:FUNC "VOLT"')
        client.send(":SENS:VOLT:RANG:AUTO ON")
        client.send(f":SOUR:CURR {source:.12g}")
    else:
        applied_compliance = min(requested_compliance, config.current_compliance)
        client.send(":SOUR:FUNC VOLT")
        client.send(":SOUR:VOLT:RANG:AUTO ON")
        client.send(f":SOUR:VOLT:ILIM {applied_compliance:.12g}")
        client.send(":SOUR:VOLT:READ:BACK ON")
        client.send(':SENS:FUNC "CURR"')
        client.send(":SENS:CURR:RANG:AUTO ON")
        client.send(f":SOUR:VOLT {source:.12g}")

    client.send(":OUTP ON")
    return applied_compliance


def measure(client: ScpiClient, mode: str) -> Measurement:
    """Acquire one coherent source-readback and sense reading pair."""
    read_command = ':READ? "defbuffer1", SOUR, READ'
    source_value, measured_value = _parse_pair_response(
        client.query(read_command), read_command
    )

    if mode == "MEAS":
        return Measurement(
            current=source_value,
            voltage=measured_value,
            state="MEAS",
        )

    if mode == "CURR":
        trip_command = ":SOUR:CURR:VLIM:TRIP?"
        tripped = _parse_scpi_bool(client.query(trip_command), trip_command)
        return Measurement(
            current=source_value,
            voltage=measured_value,
            state="VLIM" if tripped else "CURR",
        )

    trip_command = ":SOUR:VOLT:ILIM:TRIP?"
    tripped = _parse_scpi_bool(client.query(trip_command), trip_command)
    return Measurement(
        current=measured_value,
        voltage=source_value,
        state="ILIM" if tripped else "VOLT",
    )
