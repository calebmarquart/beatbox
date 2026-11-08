"""Stream Beatbox BLE notifications to a small local browser dashboard."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import queue
import threading
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer
from typing import Any

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic

DEFAULT_DEVICE_NAME = "Beatbox"
DATA_CHARACTERISTIC_UUID = "9f1c0002-4b6a-4c1e-9a52-5d3a7b2e0001"
MAX_HISTORY = 60
MAX_NOTIFICATIONS = 100
MAX_RECORD_SIZE = 4096

PAGE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Beatbox</title>
  <style>
    :root { color-scheme: light; font: 15px/1.5 ui-sans-serif, system-ui, sans-serif; background: #e7edf2; color: #111827; }
    * { box-sizing: border-box; }
    body { margin: 0; background: #e7edf2; }
    main { width: min(1100px, calc(100% - 32px)); margin: 28px auto 56px; }
    header { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 20px; padding: 0 0 18px; border-bottom: 3px solid #152b42; }
    h1 { margin: 0; color: #10263c; font-size: 1.65rem; font-weight: 750; letter-spacing: .01em; }
    h2 { margin: 0 0 14px; padding-bottom: 9px; border-bottom: 2px solid #c4ced8; color: #1b334b; font-size: .9rem; font-weight: 750; letter-spacing: .08em; text-transform: uppercase; }
    p { color: #34465a; }
    .status { display: inline-flex; align-items: center; gap: 9px; padding: 8px 12px; border: 2px solid #334155; border-radius: 0; background: #fff; color: #1e293b; font-size: .85rem; font-weight: 700; white-space: nowrap; }
    .dot { width: 10px; height: 10px; border: 1px solid #334155; border-radius: 0; background: #64748b; }
    .status.connected { border-color: #166534; color: #14532d; background: #f0fdf4; }
    .status.connected .dot { border-color: #14532d; background: #16a34a; }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
    .card { min-width: 0; padding: 18px; border: 2px solid #26384a; border-top: 5px solid #147d92; border-radius: 0; background: #fff; box-shadow: 3px 3px 0 #b9c5cf; }
    .metric { color: #10263c; font-size: 2.7rem; font-weight: 750; letter-spacing: -.03em; font-variant-numeric: tabular-nums; }
    .unit { color: #334155; font-size: 1rem; font-weight: 700; }
    .hint { min-height: 24px; margin: 3px 0 0; color: #475569; font-size: .83rem; }
    canvas { width: 100%; height: 190px; display: block; margin-top: 10px; }
    .empty { padding: 13px; border: 2px dashed #64748b; border-radius: 0; color: #334155; background: #f8fafc; font-size: .9rem; }
    #events, #packets { display: flex; flex-direction: column; gap: 8px; max-height: 240px; overflow: auto; }
    .entry { padding: 10px 12px; border: 1px solid #64748b; border-radius: 0; background: #f8fafc; color: #111827; overflow-wrap: anywhere; }
    .entry time { display: block; margin-bottom: 4px; color: #475569; font-size: .75rem; font-weight: 700; }
    .entry code { color: #172b40; font-size: .82rem; white-space: pre-wrap; }
    .event-entry { border: 2px solid #991b1b; background: #fef2f2; }
    @media (max-width: 700px) { .grid { grid-template-columns: 1fr; } header { align-items: flex-start; flex-direction: column; } }
  </style>
</head>
<body>
<main>
  <header>
    <div><h1>Beatbox</h1><p style="margin:5px 0 0">Heart rate, blood oxygen, and events</p></div>
    <div id="status" class="status"><span class="dot"></span><span id="status-text">Connecting to dashboard…</span></div>
  </header>
  <section class="grid">
    <article class="card"><h2>Heart rate</h2><div><span id="heart-rate" class="metric">--</span> <span class="unit">bpm</span></div><p id="hr-hint" class="hint">Waiting for data</p><canvas id="hr-chart" aria-label="Heart rate over time"></canvas></article>
    <article class="card"><h2>Blood oxygen</h2><div><span id="spo2" class="metric">--</span> <span class="unit">%</span></div><p id="spo2-hint" class="hint">Waiting for data</p><canvas id="spo2-chart" aria-label="Blood oxygen over time"></canvas></article>
    <article class="card"><h2>Apnea events</h2><div id="events"><div class="empty">No events yet.</div></div><p class="hint">Events reported by the data source appear here.</p></article>
    <article class="card"><h2>Incoming data</h2><div id="packets"><div class="empty">Waiting for data…</div></div></article>
  </section>
</main>
<script>
const history = { heart_rate_bpm: [], spo2_percent: [] };
const $ = (id) => document.getElementById(id);
const stamp = (value) => new Date(value).toLocaleTimeString();

function drawChart(id, points, color) {
  const canvas = $(id), rect = canvas.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.round(rect.width * dpr));
  canvas.height = Math.max(1, Math.round(rect.height * dpr));
  const ctx = canvas.getContext('2d'); ctx.scale(dpr, dpr);
  const w = rect.width, h = rect.height, left = 38, right = 8, top = 12, bottom = 23;
  ctx.clearRect(0, 0, w, h); ctx.strokeStyle = '#c4ced8'; ctx.lineWidth = 1;
  for (let i = 0; i < 4; i++) {
    const y = top + (h - top - bottom) * i / 3;
    ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(w - right, y); ctx.stroke();
  }
  if (!points.length) {
    ctx.fillStyle = '#475569'; ctx.font = '13px system-ui'; ctx.fillText('Waiting for data', left, h / 2);
    return;
  }
  const values = points.map((point) => Number(point.value));
  const dataMin = Math.min(...values), dataMax = Math.max(...values);
  const padding = Math.max((dataMax - dataMin) * .2, Math.abs(dataMax) * .005, .2);
  const min = dataMin - padding, max = dataMax + padding;
  const start = Date.parse(points[0].time), end = Date.parse(points[points.length - 1].time);
  ctx.fillStyle = '#334155'; ctx.font = '11px system-ui';
  ctx.textAlign = 'right'; ctx.fillText(max.toFixed(1), left - 6, top + 4);
  ctx.fillText(min.toFixed(1), left - 6, h - bottom + 4);
  ctx.textAlign = 'left'; ctx.fillText('OLDER', left, h - 4);
  ctx.textAlign = 'right'; ctx.fillText('NOW', w - right, h - 4);
  ctx.strokeStyle = color; ctx.lineWidth = 2.5; ctx.beginPath();
  points.forEach((point, i) => {
    const x = points.length === 1 || end === start ? (left + w - right) / 2 : left + (w - left - right) * (Date.parse(point.time) - start) / (end - start);
    const y = h - bottom - (h - top - bottom) * Math.max(0, Math.min(1, (point.value - min) / (max - min)));
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
  const latest = points[points.length - 1];
  const lastX = points.length === 1 || end === start ? (left + w - right) / 2 : w - right;
  const lastY = h - bottom - (h - top - bottom) * Math.max(0, Math.min(1, (latest.value - min) / (max - min)));
  ctx.fillStyle = color; ctx.beginPath(); ctx.arc(lastX, lastY, 4, 0, Math.PI * 2); ctx.fill();
}

function renderMetric(points, valueId, hintId, chartId, color) {
  const latest = points[points.length - 1];
  $(valueId).textContent = latest ? Number(latest.value).toFixed(1).replace(/\.0$/, '') : '--';
  $(hintId).textContent = latest ? `Latest update ${stamp(latest.time)}` : 'Waiting for data';
  drawChart(chartId, points, color);
}

function renderMetrics() {
  renderMetric(history.heart_rate_bpm, 'heart-rate', 'hr-hint', 'hr-chart', '#0067a8');
  renderMetric(history.spo2_percent, 'spo2', 'spo2-hint', 'spo2-chart', '#6b3fa0');
}

function renderSnapshot(snapshot) {
  for (const key of Object.keys(history)) history[key] = snapshot.history?.[key] || [];
  $('events').replaceChildren();
  const events = snapshot.apnea_events || [];
  if (!events.length) $('events').innerHTML = '<div class="empty">No events yet.</div>';
  for (const event of events.slice().reverse()) addApneaEvent(event, false);
  $('packets').replaceChildren();
  const packets = snapshot.notifications || [];
  if (!packets.length) $('packets').innerHTML = '<div class="empty">Waiting for notifications…</div>';
  for (const packet of packets.slice().reverse()) addPacket(packet, false);
  renderMetrics();
}

function addPacket(packet, prepend = true) {
  const box = $('packets'); if (box.querySelector('.empty')) box.replaceChildren();
  const item = document.createElement('div'); item.className = 'entry';
  const time = document.createElement('time'); time.textContent = stamp(packet.time);
  const code = document.createElement('code'); code.textContent = `${packet.hex}  |  ${packet.text || '(non-text data)'}`;
  item.append(time, code); prepend ? box.prepend(item) : box.append(item);
  while (box.children.length > 100) box.lastElementChild.remove();
}

function addApneaEvent(event, prepend = true) {
  const box = $('events'); if (box.querySelector('.empty')) box.replaceChildren();
  const item = document.createElement('div'); item.className = 'entry event-entry';
  const time = document.createElement('time'); time.textContent = stamp(event.time);
  const code = document.createElement('code'); code.textContent = event.description || 'Apnea event reported by device';
  item.append(time, code); prepend ? box.prepend(item) : box.append(item);
}

function setStatus(text, connected) {
  $('status-text').textContent = text; $('status').classList.toggle('connected', connected);
}

const source = new EventSource('/events');
source.onopen = () => setStatus('Connected', true);
source.onerror = () => setStatus('Reconnecting to dashboard…', false);
source.addEventListener('snapshot', (event) => renderSnapshot(JSON.parse(event.data)));
source.addEventListener('ble_status', (event) => {
  const data = JSON.parse(event.data);
  setStatus(data.connected ? `${data.device} connected` : data.message, data.connected);
});
source.addEventListener('notification', (event) => addPacket(JSON.parse(event.data)));
source.addEventListener('measurement', (event) => {
  const data = JSON.parse(event.data);
  for (const key of Object.keys(history)) if (data[key] !== undefined) {
    history[key].push({ time: data.time, value: data[key] });
    history[key] = history[key].slice(-60);
  }
  renderMetrics();
});
source.addEventListener('apnea_event', (event) => addApneaEvent(JSON.parse(event.data)));
window.addEventListener('resize', renderMetrics);
</script>
</body>
</html>"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class DashboardState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.subscribers: set[queue.Queue[tuple[str, dict[str, Any]]]] = set()
        self.history: dict[str, list[dict[str, Any]]] = {
            "heart_rate_bpm": [],
            "spo2_percent": [],
        }
        self.notifications: list[dict[str, Any]] = []
        self.apnea_events: list[dict[str, Any]] = []

    def publish(self, event: str, data: dict[str, Any]) -> None:
        with self.lock:
            subscribers = tuple(self.subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait((event, data))
            except queue.Full:
                try:
                    subscriber.get_nowait()
                    subscriber.put_nowait((event, data))
                except queue.Empty:
                    pass

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "history": {key: list(points) for key, points in self.history.items()},
                "notifications": list(self.notifications),
                "apnea_events": list(self.apnea_events),
            }

    def add_notification(self, raw: bytes) -> None:
        now = utc_now()
        text = raw.decode("utf-8", errors="replace").rstrip("\x00\r\n")
        packet = {"time": now, "hex": raw.hex(" "), "text": text}
        with self.lock:
            self.notifications.append(packet)
            del self.notifications[:-MAX_NOTIFICATIONS]
        self.publish("notification", packet)

    def add_record(self, raw: bytes) -> None:
        try:
            message = json.loads(raw.decode("utf-8").strip())
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
            return
        if not isinstance(message, dict):
            return

        now = utc_now()
        measurement: dict[str, Any] = {"time": now}
        for key, minimum, maximum in (
            ("heart_rate_bpm", 0, 300),
            ("spo2_percent", 0, 100),
        ):
            value = message.get(key)
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                and minimum <= value <= maximum
            ):
                measurement[key] = value

        if len(measurement) > 1:
            with self.lock:
                for key in self.history:
                    if key in measurement:
                        self.history[key].append(
                            {"time": now, "value": measurement[key]}
                        )
                        del self.history[key][:-MAX_HISTORY]
            self.publish("measurement", measurement)

        apnea = message.get("apnea_event")
        if apnea:
            if isinstance(apnea, str):
                description = apnea
            elif isinstance(apnea, dict):
                description = str(
                    apnea.get("description")
                    or apnea.get("type")
                    or "Apnea event reported by device"
                )
            else:
                description = "Apnea event reported by device"
            event = {"time": now, "description": description}
            with self.lock:
                self.apnea_events.append(event)
                del self.apnea_events[:-MAX_NOTIFICATIONS]
            self.publish("apnea_event", event)


STATE = DashboardState()


class DashboardHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        if self.path == "/":
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/events":
            self._stream_events()
            return
        self.send_error(404)

    def _stream_events(self) -> None:
        subscriber: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue(maxsize=128)
        with STATE.lock:
            STATE.subscribers.add(subscriber)
            snapshot = {
                "history": {key: list(points) for key, points in STATE.history.items()},
                "notifications": list(STATE.notifications),
                "apnea_events": list(STATE.apnea_events),
            }
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            self._write_event("snapshot", snapshot)
            while True:
                try:
                    event, data = subscriber.get(timeout=15)
                    self._write_event(event, data)
                except queue.Empty:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
            pass
        finally:
            with STATE.lock:
                STATE.subscribers.discard(subscriber)

    def _write_event(self, event: str, data: dict[str, Any]) -> None:
        payload = json.dumps(data, separators=(",", ":"))
        self.wfile.write(f"event: {event}\ndata: {payload}\n\n".encode())
        self.wfile.flush()

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[http] {self.address_string()} - {format % args}")


def start_web_server(host: str, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    thread = threading.Thread(
        target=server.serve_forever, name="dashboard-http", daemon=True
    )
    thread.start()
    return server


async def run_ble(device_name: str, characteristic_uuid: str) -> None:
    while True:
        STATE.publish(
            "ble_status",
            {"connected": False, "message": f"Scanning for {device_name}…"},
        )
        print(f"Scanning for BLE device {device_name!r}...")
        try:
            device = await BleakScanner.find_device_by_name(device_name, timeout=30.0)
            if device is None:
                STATE.publish(
                    "ble_status",
                    {
                        "connected": False,
                        "message": f"Could not find {device_name}; retrying",
                    },
                )
                await asyncio.sleep(3)
                continue

            name = device.name or device_name
            print(f"Found {name} ({device.address}); connecting...")
            STATE.publish(
                "ble_status", {"connected": False, "message": f"Connecting to {name}…"}
            )
            async with BleakClient(device) as client:
                record_buffer = bytearray()

                def on_notification(
                    _sender: BleakGATTCharacteristic, data: bytearray
                ) -> None:
                    packet = bytes(data)
                    STATE.add_notification(packet)
                    print(
                        f"Notification ({len(packet)} bytes): {packet.hex(' ')}",
                        flush=True,
                    )
                    record_buffer.extend(packet)
                    while b"\n" in record_buffer:
                        record, _, remainder = record_buffer.partition(b"\n")
                        record_buffer[:] = remainder
                        STATE.add_record(record)
                    if len(record_buffer) > MAX_RECORD_SIZE:
                        record_buffer.clear()

                await client.start_notify(characteristic_uuid, on_notification)
                STATE.publish("ble_status", {"connected": True, "device": name})
                print(
                    f"Connected; forwarding notifications to the dashboard for {name}."
                )
                while client.is_connected:
                    await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            message = f"BLE error: {exc}; retrying"
            print(message)
            STATE.publish("ble_status", {"connected": False, "message": message})
        await asyncio.sleep(2)


async def run_demo() -> None:
    print("Using generated demo data; press Ctrl+C to stop.")
    STATE.publish("ble_status", {"connected": True, "device": "Demo data"})
    tick = 0
    while True:
        record: dict[str, Any] = {
            "heart_rate_bpm": round(
                72 + 5 * math.sin(tick / 5) + 1.5 * math.sin(tick / 2), 1
            ),
            "spo2_percent": round(97.2 + 0.8 * math.sin(tick / 7), 1),
        }
        if tick == 5 or (tick > 5 and tick % 30 == 5):
            record["apnea_event"] = {"type": "demo", "description": "Demo apnea event"}
        raw = json.dumps(record, separators=(",", ":")).encode("utf-8")
        STATE.add_notification(raw)
        STATE.add_record(raw)
        tick += 1
        await asyncio.sleep(2)


async def serve(
    device_name: str, characteristic_uuid: str, host: str, port: int, demo: bool
) -> None:
    server = start_web_server(host, port)
    print(f"Dashboard running at http://{host}:{port}")
    try:
        if demo:
            await run_demo()
        else:
            await run_ble(device_name, characteristic_uuid)
    finally:
        server.shutdown()
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--name",
        default=DEFAULT_DEVICE_NAME,
        help=f"BLE device name (default: {DEFAULT_DEVICE_NAME})",
    )
    parser.add_argument(
        "--characteristic",
        default=DATA_CHARACTERISTIC_UUID,
        help=f"notification characteristic UUID (default: {DATA_CHARACTERISTIC_UUID})",
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="HTTP bind address; default is local-only"
    )
    parser.add_argument(
        "--port", type=int, default=8000, help="HTTP port (default: 8000)"
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="use generated sample data instead of connecting over BLE",
    )
    args = parser.parse_args()
    try:
        asyncio.run(
            serve(args.name, args.characteristic, args.host, args.port, args.demo)
        )
    except KeyboardInterrupt:
        print("\nShutting down dashboard.")


if __name__ == "__main__":
    main()
