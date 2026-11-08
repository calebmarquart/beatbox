# Beatbox BLE tools

These scripts connect to the ESP32 BLE peripheral advertised as `Beatbox` and subscribe to its UART data characteristic. `ble_listener.py` prints notifications in the terminal. `dashboard.py` also serves a live browser dashboard.

## Setup

Install [uv](https://docs.astral.sh/uv/), then sync the locked dependencies from this directory:

```sh
uv sync --locked
```

## Terminal listener

```sh
uv run ble_listener.py
```

## Browser dashboard

Preview the dashboard with generated sample data, without a BLE device:

```sh
uv run dashboard.py --demo
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Demo values update every two seconds and include a sample event. For the BLE stream, run `uv run dashboard.py`; it reconnects if the device connection drops. Use `--name` or `--characteristic` to override the BLE defaults, and `--host` or `--port` to change the local web server address. Press Ctrl+C to stop.

For BLE measurements, send newline-delimited UTF-8 JSON records, for example:

```json
{"heart_rate_bpm":72,"spo2_percent":98,"apnea_event":null}
{"heart_rate_bpm":74,"spo2_percent":97,"apnea_event":{"type":"apnea","description":"Apnea event detected"}}
```

Records can span multiple BLE notifications; the dashboard joins chunks until the newline. `heart_rate_bpm` and `spo2_percent` are optional numeric fields. A truthy `apnea_event` adds an event to the event list. The dashboard displays events reported by the data source; it does not infer apnea from the measurements.
