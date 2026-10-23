#!/usr/bin/env bash
# Uso: ./run_test.sh <configfile> <inputfile> <outputfile>
# Richiede Bash: eseguire con ./run_test.sh oppure bash run_test.sh.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PATH="$SCRIPT_DIR/$(basename -- "${BASH_SOURCE[0]}")"

# Percorsi relativi alla cartella dello script.
VENV_DIR="$SCRIPT_DIR/.env"
MAIN_PY="$SCRIPT_DIR/battery-cycler/main.py"

# Configurazione broker MQTT: modificare questi valori.
MQTT_HOST="127.0.0.1"
MQTT_PORT="1883"
MQTT_TOPIC="beast-lab/measures"
MQTT_USER=""                    # Vuoto se non serve autenticazione.
MQTT_PASSWORD=""
MQTT_QOS="1"

die() {
    printf 'Errore: %s\n' "$*" >&2
    exit 1
}

# Opzione interna: screen richiama lo script per eseguire la pipeline.
INSIDE_SCREEN=0
if [[ ${1:-} == --inside-screen ]]; then
    INSIDE_SCREEN=1
    shift
fi

if [[ $# -ne 3 ]]; then
    printf 'Uso: %s <configfile> <inputfile> <outputfile>\n' "$0" >&2
    exit 2
fi

CONFIGFILE="$1"
INPUTFILE="$2"
OUTPUTFILE="$3"

[[ -f "$CONFIGFILE" && -r "$CONFIGFILE" ]] || die "Config non leggibile: $CONFIGFILE"
[[ -f "$INPUTFILE" && -r "$INPUTFILE" ]] || die "Input non leggibile: $INPUTFILE"
[[ -f "$MAIN_PY" && -r "$MAIN_PY" ]] || die "Programma non leggibile: $MAIN_PY"
[[ -r "$VENV_DIR/bin/activate" ]] || die "Virtualenv non trovato: $VENV_DIR"

if [[ $INSIDE_SCREEN -eq 0 ]]; then
    command -v screen >/dev/null 2>&1 || die "Installare screen."

    # /percorso/prova.01.csv -> prova.01
    SESSION_NAME="${OUTPUTFILE##*/}"
    SESSION_NAME="${SESSION_NAME%.*}"
    [[ -n "$SESSION_NAME" ]] || die "Nome della sessione vuoto."

    # Sessione visibile. Ctrl+A, poi D per scollegarsi lasciandola attiva.
    # Gli argomenti mantengono anche spazi e caratteri speciali.
    exec screen -m -S "$SESSION_NAME" bash "$SCRIPT_PATH" --inside-screen "$@"
fi

# Attiva il virtualenv dentro screen, prima di avviare Python.
source "$VENV_DIR/bin/activate"
command -v python >/dev/null 2>&1 || die "Python non disponibile nel virtualenv."
#command -v mosquitto_pub >/dev/null 2>&1 || die "Installare mosquitto-clients."
command -v tee >/dev/null 2>&1 || die "Comando tee non disponibile."

MQTT_ARGS=(-h "$MQTT_HOST" -p "$MQTT_PORT" -t "$MQTT_TOPIC" -q "$MQTT_QOS" -l)
if [[ -n "$MQTT_USER" ]]; then
    MQTT_ARGS+=(-u "$MQTT_USER" -P "$MQTT_PASSWORD")
fi

# -u: stdout Python senza buffering.
# tee: duplica lo stdout sul terminale di screen e nella pipe MQTT.
# -l: ogni riga diventa un messaggio; emettere un JSON completo per riga.
# stderr resta sul terminale e non viene pubblicato.
# Si assume che main.py accetti i tre argomenti posizionali qui sotto.
# Il salvataggio di OUTPUTFILE e' gestito da main.py.
python -u "$MAIN_PY" --config "$CONFIGFILE" --input "$INPUTFILE" --output "$OUTPUTFILE" 
