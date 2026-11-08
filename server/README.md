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

Preview the dashboard with generated sample data at 100 samples per second, without a BLE device:

```sh
uv run dashboard.py --demo
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). For the BLE stream, run `uv run dashboard.py`; it reconnects if the device connection drops. Use `--name` or `--characteristic` to override the BLE defaults, and `--host` or `--port` to change the local web server address. Press Ctrl+C to stop.

Each sample is an ASCII line containing two comma-separated absorbance values, which may use scientific notation: `red_absorbance,ir_absorbance\n`. The dashboard parses and uses the values as-is, without rescaling. A line is at most 23 bytes. Samples are timestamped at 100 Hz (10 ms apart). The listener joins notification chunks until the line ending, so a sample can span BLE notifications.

The dashboard estimates heart rate from red absorbance using a 1-second moving-average baseline, 5-sample smoothing, prominence-based peak detection, and peak spacing. It estimates SpO₂ from 5-second red and infrared windows using peak-to-peak AC, mean DC, and `SpO₂ = 110 - 25R`. This empirical calculation on absorbance values is only an approximation and is not suitable for medical use.
