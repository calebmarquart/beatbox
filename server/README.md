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

The dashboard saves all six values from each sample to `server/beatbox_history.sqlite3`. Use the **History** tab to browse saved rows; **Load older samples** pages through the database. History and Events each have a time-range filter, show newest entries first, and support paging to older entries within the selected range. The CSV download includes the displayed values and omits ratio. The SQLite file is local and excluded from Git.

The red and IR integers are displayed and saved as received, with no display multiplier.

Live graphs automatically scale and offset vertically to fit the visible samples. Use **Time +** and **Time −** to adjust the horizontal window; **Reset** returns it to 6 seconds.

The **Events** tab lists timestamped events saved in SQLite. The sleep apnea threshold slider defaults to `0.26` and applies to event recording and the browser alarm. An event is recorded once when probability crosses above the configured threshold. Click **Apnea alarm: Off** to arm the browser alarm; it sounds repeatedly while probability remains above the threshold.

Each sample is an ASCII line containing six comma-separated values: `red_integer,ir_integer,heart_rate_bpm,spo2_percent,ratio,apnea_probability\n`. The first two values are integers; heart rate and SpO₂ are streamed metrics; ratio is a decimal from -1 to 1; apnea probability is a decimal from 0 to 1. Ratio is still accepted and saved in SQLite but is omitted from the dashboard and CSV. A value of `-1` means unavailable for heart rate, SpO₂, ratio, and apnea probability; it is retained in SQLite and shown as `--` where displayed. A probability over the configured threshold raises an event and, when the browser alarm is armed, sounds the alarm. A line is at most 48 bytes. Samples are timestamped at 100 Hz (10 ms apart). The listener joins notification chunks until the line ending, so a sample can span BLE notifications.

The dashboard plots red, IR, heart rate, SpO₂, and apnea probability without deriving heart rate or SpO₂ locally.
