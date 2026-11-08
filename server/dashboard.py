"""Stream Beatbox BLE notifications to a small local browser dashboard."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import queue
import threading
from collections import deque
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic

DEFAULT_DEVICE_NAME = "Beatbox"
DATA_CHARACTERISTIC_UUID = "9f1c0002-4b6a-4c1e-9a52-5d3a7b2e0001"
MAX_HISTORY = 3000
MAX_NOTIFICATIONS = 100
SAMPLE_RATE_HZ = 100
MAX_RECORD_SIZE = 23
DC_WINDOW_SAMPLES = SAMPLE_RATE_HZ
SPO2_WINDOW_SAMPLES = 5 * SAMPLE_RATE_HZ
HR_MIN_PEAK_DISTANCE = 30
HR_MAX_PEAK_DISTANCE = 200

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
    .header-actions { display: flex; align-items: center; gap: 10px; }
    .download { padding: 8px 12px; border: 2px solid #152b42; border-radius: 0; background: #152b42; color: #fff; font: inherit; font-size: .85rem; font-weight: 700; cursor: pointer; }
    .download:hover { background: #26384a; }
    .dot { width: 10px; height: 10px; border: 1px solid #334155; border-radius: 0; background: #64748b; }
    .status.connected { border-color: #166534; color: #14532d; background: #f0fdf4; }
    .status.connected .dot { border-color: #14532d; background: #16a34a; }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
    .card { min-width: 0; padding: 18px; border: 2px solid #26384a; border-top: 5px solid #147d92; border-radius: 0; background: #fff; box-shadow: 3px 3px 0 #b9c5cf; }
    .wide { grid-column: 1 / -1; }
    .metric { color: #10263c; font-size: 2.7rem; font-weight: 750; letter-spacing: -.03em; font-variant-numeric: tabular-nums; }
    .unit { color: #334155; font-size: 1rem; font-weight: 700; }
    .hint { min-height: 24px; margin: 3px 0 0; color: #475569; font-size: .83rem; }
    .chart-controls { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
    .chart-controls button { padding: 4px 8px; border: 1px solid #64748b; border-radius: 0; background: #f8fafc; color: #1e293b; font: inherit; font-size: .78rem; font-weight: 700; cursor: pointer; }
    .chart-controls button:hover { background: #e2e8f0; }
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
    <div><h1>Beatbox</h1><p style="margin:5px 0 0">Red and infrared absorbance</p></div>
    <div class="header-actions"><button id="download" class="download" type="button">Download CSV</button><div id="status" class="status"><span class="dot"></span><span id="status-text">Connecting to dashboard…</span></div></div>
  </header>
  <section class="grid">
    <article class="card"><h2>Red absorbance</h2><div><span id="red-current" class="metric">--</span></div><p id="red-hint" class="hint">Waiting for data</p><canvas id="red-chart" aria-label="Red absorbance over time"></canvas><div class="chart-controls" data-chart="red-chart"><button type="button" data-action="zoom-in">Vertical +</button><button type="button" data-action="zoom-out">Vertical −</button><button type="button" data-action="shift-up">Offset ↑</button><button type="button" data-action="shift-down">Offset ↓</button><button type="button" data-action="time-in" title="Zoom in horizontally">Time +</button><button type="button" data-action="time-out" title="Zoom out horizontally">Time −</button><button type="button" data-action="reset">Reset</button></div></article>
    <article class="card"><h2>Infrared absorbance</h2><div><span id="ir-current" class="metric">--</span></div><p id="ir-hint" class="hint">Waiting for data</p><canvas id="ir-chart" aria-label="Infrared absorbance over time"></canvas><div class="chart-controls" data-chart="ir-chart"><button type="button" data-action="zoom-in">Vertical +</button><button type="button" data-action="zoom-out">Vertical −</button><button type="button" data-action="shift-up">Offset ↑</button><button type="button" data-action="shift-down">Offset ↓</button><button type="button" data-action="time-in" title="Zoom in horizontally">Time +</button><button type="button" data-action="time-out" title="Zoom out horizontally">Time −</button><button type="button" data-action="reset">Reset</button></div></article>
    <article class="card wide"><h2>Red and infrared absorbance</h2><p class="hint"><span style="color:#b42318;font-weight:700">Red</span> · <span style="color:#6b3fa0;font-weight:700">Infrared</span></p><canvas id="combined-chart" aria-label="Red and infrared absorbance over time"></canvas><div class="chart-controls" data-chart="combined-chart"><button type="button" data-action="zoom-in">Vertical +</button><button type="button" data-action="zoom-out">Vertical −</button><button type="button" data-action="shift-up">Offset ↑</button><button type="button" data-action="shift-down">Offset ↓</button><button type="button" data-action="time-in" title="Zoom in horizontally">Time +</button><button type="button" data-action="time-out" title="Zoom out horizontally">Time −</button><button type="button" data-action="reset">Reset</button></div></article>
    <article class="card wide"><h2>Red / IR absorbance ratio</h2><div><span id="reflectance-value" class="metric">--</span></div><p class="hint">Red absorbance ÷ infrared absorbance; ratio proxy, not calibrated reflectance</p><canvas id="reflectance-chart" aria-label="Red to infrared absorbance ratio over time"></canvas><div class="chart-controls" data-chart="reflectance-chart"><button type="button" data-action="zoom-in">Vertical +</button><button type="button" data-action="zoom-out">Vertical −</button><button type="button" data-action="shift-up">Offset ↑</button><button type="button" data-action="shift-down">Offset ↓</button><button type="button" data-action="time-in" title="Zoom in horizontally">Time +</button><button type="button" data-action="time-out" title="Zoom out horizontally">Time −</button><button type="button" data-action="reset">Reset</button></div></article>
    <article class="card"><h2>Heart rate estimate</h2><div><span id="heart-rate" class="metric">--</span> <span class="unit">BPM</span></div><p id="hr-hint" class="hint">Waiting for enough red samples</p></article>
    <article class="card"><h2>SpO₂ estimate</h2><div><span id="spo2-estimate" class="metric">--</span> <span class="unit">%</span></div><p id="spo2-hint" class="hint">Approximate only; not for medical use</p></article>
    <article class="card"><h2>Incoming data</h2><div id="packets"><div class="empty">Waiting for data…</div></div></article>
  </section>
</main>
<script>
const history = { red_absorbance: [], ir_absorbance: [] };
const DEFAULT_CHART_MIN = 0;
const DEFAULT_CHART_MAX = 0.05;
const chartRanges = {
  'red-chart': { min: DEFAULT_CHART_MIN, max: DEFAULT_CHART_MAX, windowSeconds: 6 },
  'ir-chart': { min: DEFAULT_CHART_MIN, max: DEFAULT_CHART_MAX, windowSeconds: 6 },
  'combined-chart': { min: DEFAULT_CHART_MIN, max: DEFAULT_CHART_MAX, windowSeconds: 6 },
  'reflectance-chart': { min: 0, max: 2, windowSeconds: 6 },
};
const samples = new Map();
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
  const range = chartRanges[id];
  const { min, max } = range;
  const end = Date.parse(points[points.length - 1].time);
  const start = end - range.windowSeconds * 1000;
  const visiblePoints = points.filter((point) => Date.parse(point.time) >= start);
  ctx.fillStyle = '#334155'; ctx.font = '11px system-ui';
  ctx.textAlign = 'right'; ctx.fillText(max.toPrecision(4), left - 6, top + 4);
  ctx.fillText(min.toPrecision(4), left - 6, h - bottom + 4);
  ctx.textAlign = 'left'; ctx.fillText('OLDER', left, h - 4);
  ctx.textAlign = 'right'; ctx.fillText('NOW', w - right, h - 4);
  ctx.strokeStyle = color; ctx.lineWidth = 2.5; ctx.beginPath();
  visiblePoints.forEach((point, i) => {
    const x = left + (w - left - right) * (Date.parse(point.time) - start) / (end - start);
    const y = h - bottom - (h - top - bottom) * Math.max(0, Math.min(1, (point.value - min) / (max - min)));
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
  const latest = visiblePoints[visiblePoints.length - 1];
  const lastX = left + (w - left - right) * (Date.parse(latest.time) - start) / (end - start);
  const lastY = h - bottom - (h - top - bottom) * Math.max(0, Math.min(1, (latest.value - min) / (max - min)));
  ctx.fillStyle = color; ctx.beginPath(); ctx.arc(lastX, lastY, 4, 0, Math.PI * 2); ctx.fill();
}

function renderMetric(points, valueId, hintId, chartId, color) {
  const latest = points[points.length - 1];
  $(valueId).textContent = latest
    ? Number(latest.value).toPrecision(6)
    : '--';
  $(hintId).textContent = latest ? `Latest update ${stamp(latest.time)}` : 'Waiting for data';
  drawChart(chartId, points, color);
}

function renderMetrics() {
  renderMetric(history.red_absorbance, 'red-current', 'red-hint', 'red-chart', '#b42318');
  renderMetric(history.ir_absorbance, 'ir-current', 'ir-hint', 'ir-chart', '#6b3fa0');
  drawCombinedChart();
  const irByTime = new Map(
    history.ir_absorbance.map((point) => [point.time, point.value]),
  );
  const ratioPoints = history.red_absorbance.flatMap((point) => {
    const ir = irByTime.get(point.time);
    if (ir === undefined || ir === 0) return [];
    return [{ time: point.time, value: point.value / ir }];
  });
  const latestRatio = ratioPoints[ratioPoints.length - 1];
  $('reflectance-value').textContent = latestRatio
    ? Number(latestRatio.value).toPrecision(6)
    : '--';
  drawChart('reflectance-chart', ratioPoints, '#0f766e');
}

function drawCombinedChart() {
  const redPoints = history.red_absorbance;
  const irPoints = history.ir_absorbance;
  const allPoints = redPoints.length ? redPoints : irPoints;
  const canvas = $('combined-chart');
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.round(rect.width * dpr));
  canvas.height = Math.max(1, Math.round(rect.height * dpr));
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  const w = rect.width, h = rect.height, left = 42, right = 8, top = 12, bottom = 23;
  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = '#c4ced8';
  ctx.lineWidth = 1;
  for (let i = 0; i < 4; i++) {
    const y = top + (h - top - bottom) * i / 3;
    ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(w - right, y); ctx.stroke();
  }
  if (!allPoints.length) {
    ctx.fillStyle = '#475569'; ctx.font = '13px system-ui';
    ctx.fillText('Waiting for data', left, h / 2);
    return;
  }
  const range = chartRanges['combined-chart'];
  const end = Date.parse(allPoints[allPoints.length - 1].time);
  const start = end - range.windowSeconds * 1000;
  ctx.fillStyle = '#334155'; ctx.font = '11px system-ui';
  ctx.textAlign = 'right';
  ctx.fillText(range.max.toPrecision(4), left - 6, top + 4);
  ctx.fillText(range.min.toPrecision(4), left - 6, h - bottom + 4);
  ctx.textAlign = 'left'; ctx.fillText('OLDER', left, h - 4);
  ctx.textAlign = 'right'; ctx.fillText('NOW', w - right, h - 4);
  for (const [points, color] of [
    [redPoints, '#b42318'],
    [irPoints, '#6b3fa0'],
  ]) {
    const visiblePoints = points.filter((point) => Date.parse(point.time) >= start);
    if (!visiblePoints.length) continue;
    ctx.strokeStyle = color;
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    visiblePoints.forEach((point, i) => {
      const x = left + (w - left - right) * (Date.parse(point.time) - start) / (end - start);
      const y = h - bottom - (h - top - bottom)
        * Math.max(0, Math.min(1, (point.value - range.min) / (range.max - range.min)));
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
    const latest = visiblePoints[visiblePoints.length - 1];
    const lastX = left + (w - left - right) * (Date.parse(latest.time) - start) / (end - start);
    const lastY = h - bottom - (h - top - bottom)
      * Math.max(0, Math.min(1, (latest.value - range.min) / (range.max - range.min)));
    ctx.fillStyle = color;
    ctx.beginPath(); ctx.arc(lastX, lastY, 4, 0, Math.PI * 2); ctx.fill();
  }
}

function renderCalculatedMetrics(metrics = {}) {
  const heartRate = metrics.heart_rate_bpm;
  const spo2 = metrics.spo2_estimate_percent;
  $('heart-rate').textContent = heartRate == null ? '--' : Number(heartRate).toFixed(0);
  $('hr-hint').textContent = heartRate == null
    ? 'Waiting for two valid red peaks'
    : 'Estimated from smoothed red peaks';
  $('spo2-estimate').textContent = spo2 == null ? '--' : Number(spo2).toFixed(1);
  $('spo2-hint').textContent = spo2 == null
    ? 'Collecting 5 seconds of red and IR samples'
    : 'Approximate only; not for medical use';
}

function adjustChartRange(id, action) {
  const range = chartRanges[id];
  const center = (range.min + range.max) / 2;
  const span = range.max - range.min;
  if (action === 'zoom-in' || action === 'zoom-out') {
    const nextSpan = span * (action === 'zoom-in' ? 0.8 : 1.25);
    range.min = center - nextSpan / 2;
    range.max = center + nextSpan / 2;
  } else if (action === 'shift-up' || action === 'shift-down') {
    const offset = span * 0.1 * (action === 'shift-up' ? 1 : -1);
    range.min += offset;
    range.max += offset;
  } else if (action === 'time-in' || action === 'time-out') {
    const factor = action === 'time-in' ? 0.8 : 1.25;
    range.windowSeconds = Math.max(0.2, Math.min(30, range.windowSeconds * factor));
  } else if (action === 'reset') {
    range.min = id === 'reflectance-chart' ? 0 : DEFAULT_CHART_MIN;
    range.max = id === 'reflectance-chart' ? 2 : DEFAULT_CHART_MAX;
    range.windowSeconds = 6;
  }
  renderMetrics();
}

function renderSnapshot(snapshot) {
  for (const key of Object.keys(history)) history[key] = snapshot.history?.[key] || [];
  renderCalculatedMetrics(snapshot.metrics);
  const infraredByTime = new Map(
    history.ir_absorbance.map((point) => [point.time, point.value]),
  );
  for (const point of history.red_absorbance) {
    const ir = infraredByTime.get(point.time);
    if (ir !== undefined) {
      samples.set(point.time, {
        timestamp: point.time,
        red_absorbance: point.value,
        ir_absorbance: ir,
      });
    }
  }
  $('packets').replaceChildren();
  const packets = snapshot.notifications || [];
  if (!packets.length) $('packets').innerHTML = '<div class="empty">Waiting for notifications…</div>';
  for (const packet of packets.slice().reverse()) addPacket(packet, false);
  renderMetrics();
}

function downloadSamples() {
  const rows = ['timestamp,red_absorbance,ir_absorbance'];
  const orderedSamples = Array.from(samples.values()).sort((a, b) =>
    a.timestamp.localeCompare(b.timestamp),
  );
  for (const sample of orderedSamples) {
    rows.push(`${sample.timestamp},${sample.red_absorbance},${sample.ir_absorbance}`);
  }
  const blob = new Blob(['\uFEFF', rows.join('\r\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'beatbox-samples.csv';
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function addPacket(packet, prepend = true) {
  const box = $('packets'); if (box.querySelector('.empty')) box.replaceChildren();
  const item = document.createElement('div'); item.className = 'entry';
  const time = document.createElement('time'); time.textContent = stamp(packet.time);
  const code = document.createElement('code'); code.textContent = `${packet.hex}  |  ${packet.text || '(non-text data)'}`;
  item.append(time, code); prepend ? box.prepend(item) : box.append(item);
  while (box.children.length > 100) box.lastElementChild.remove();
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
  renderCalculatedMetrics(data);
  samples.set(data.time, {
    timestamp: data.time,
    red_absorbance: data.red_absorbance,
    ir_absorbance: data.ir_absorbance,
  });
  for (const key of Object.keys(history)) if (data[key] !== undefined) {
    history[key].push({ time: data.time, value: data[key] });
    history[key] = history[key].slice(-3000);
  }
  renderMetrics();
});
$("download").addEventListener('click', downloadSamples);
document.querySelectorAll('.chart-controls').forEach((controls) => {
  controls.addEventListener('click', (event) => {
    const button = event.target.closest('button');
    if (button) adjustChartRange(controls.dataset.chart, button.dataset.action);
  });
});
window.addEventListener('resize', renderMetrics);
</script>
</body>
</html>"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class DashboardState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.subscribers: set[queue.Queue[tuple[str, dict[str, Any]]]] = set()
        self.history: dict[str, list[dict[str, Any]]] = {
            "red_absorbance": [],
            "ir_absorbance": [],
        }
        self.notifications: list[dict[str, Any]] = []
        self.last_sample_time: datetime | None = None
        self.sample_index = 0
        self.red_window: deque[float] = deque(maxlen=SPO2_WINDOW_SAMPLES)
        self.ir_window: deque[float] = deque(maxlen=SPO2_WINDOW_SAMPLES)
        self.red_dc_window: deque[float] = deque(maxlen=DC_WINDOW_SAMPLES)
        self.red_ac_smoothing: deque[float] = deque(maxlen=5)
        self.red_smoothed_window: deque[float] = deque(maxlen=3)
        self.red_ac_history: deque[float] = deque(maxlen=3 * SAMPLE_RATE_HZ)
        self.last_hr_peak_index: int | None = None
        self.hr_peak_intervals: deque[int] = deque(maxlen=3)
        self.hr_valley = math.inf
        self.latest_metrics: dict[str, float | None] = {
            "heart_rate_bpm": None,
            "spo2_estimate_percent": None,
        }

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
                "metrics": dict(self.latest_metrics),
            }

    def add_notification(self, raw: bytes) -> None:
        now = utc_now()
        text = raw.decode("ascii", errors="replace").strip()
        if not text:
            text = f"{len(raw)} bytes received"
        packet = {"time": now, "hex": raw.hex(" "), "text": text}
        with self.lock:
            self.notifications.append(packet)
            del self.notifications[:-MAX_NOTIFICATIONS]
        self.publish("notification", packet)

    def add_record(self, raw: bytes) -> None:
        try:
            fields = raw.decode("ascii").strip().split(",")
            if len(fields) != 2:
                return
            red_absorbance, ir_absorbance = (
                float(field.strip()) for field in fields
            )
        except (UnicodeDecodeError, ValueError):
            return
        if not (math.isfinite(red_absorbance) and math.isfinite(ir_absorbance)):
            return
        with self.lock:
            if self.last_sample_time is None:
                self.last_sample_time = datetime.now(UTC)
            else:
                self.last_sample_time += timedelta(seconds=1 / SAMPLE_RATE_HZ)
            sample_time = self.last_sample_time.isoformat(timespec="milliseconds")
            measurement: dict[str, Any] = {
                "time": sample_time,
                "red_absorbance": red_absorbance,
                "ir_absorbance": ir_absorbance,
            }
            self.sample_index += 1
            self.red_window.append(red_absorbance)
            self.ir_window.append(ir_absorbance)
            self.latest_metrics["heart_rate_bpm"] = self._estimate_heart_rate(
                red_absorbance
            )
            self.latest_metrics["spo2_estimate_percent"] = self._estimate_spo2()
            measurement.update(self.latest_metrics)
            for key in self.history:
                self.history[key].append(
                    {"time": sample_time, "value": measurement[key]}
                )
                del self.history[key][:-MAX_HISTORY]
        print(
            f"{sample_time} red={red_absorbance:.6g} IR={ir_absorbance:.6g}",
            flush=True,
        )
        self.publish("measurement", measurement)

    def _estimate_heart_rate(self, red_absorbance: float) -> float | None:
        self.red_dc_window.append(red_absorbance)
        dc = math.fsum(self.red_dc_window) / len(self.red_dc_window)
        ac = red_absorbance - dc
        self.red_ac_smoothing.append(ac)
        smoothed_ac = math.fsum(self.red_ac_smoothing) / len(self.red_ac_smoothing)
        self.red_smoothed_window.append(smoothed_ac)
        self.red_ac_history.append(smoothed_ac)
        self.hr_valley = min(self.hr_valley, smoothed_ac)

        bpm = self.latest_metrics["heart_rate_bpm"]
        if (
            self.last_hr_peak_index is not None
            and self.sample_index - self.last_hr_peak_index > HR_MAX_PEAK_DISTANCE
        ):
            bpm = None
            self.hr_peak_intervals.clear()

        if len(self.red_smoothed_window) == 3:
            left, center, right = self.red_smoothed_window
            signal_min = min(self.red_ac_history)
            signal_max = max(self.red_ac_history)
            signal_range = signal_max - signal_min
            noise_floor = max(abs(dc) * 0.001, 1e-9)
            threshold = max(signal_min + 0.35 * signal_range, noise_floor)
            peak_index = self.sample_index - 1
            if (
                signal_range >= noise_floor
                and center > left
                and center >= right
                and center > threshold
                and center - self.hr_valley
                >= max(noise_floor * 1.5, signal_range * 0.25)
            ):
                if self.last_hr_peak_index is None:
                    self.last_hr_peak_index = peak_index
                    self.hr_valley = right
                else:
                    separation = peak_index - self.last_hr_peak_index
                    if separation >= HR_MIN_PEAK_DISTANCE:
                        self.last_hr_peak_index = peak_index
                        if separation <= HR_MAX_PEAK_DISTANCE:
                            self.hr_peak_intervals.append(separation)
                            average_interval = math.fsum(self.hr_peak_intervals) / len(
                                self.hr_peak_intervals
                            )
                            interval_seconds = average_interval / SAMPLE_RATE_HZ
                            bpm = 60 / interval_seconds
                            print(
                                f"Red peak interval {interval_seconds:.3f} s: "
                                f"heart rate {bpm:.1f} BPM",
                                flush=True,
                            )
                        else:
                            bpm = None
                            self.hr_peak_intervals.clear()
                        self.hr_valley = right
        return bpm

    def _estimate_spo2(self) -> float | None:
        if len(self.red_window) < SPO2_WINDOW_SAMPLES:
            return None
        red_dc = math.fsum(self.red_window) / len(self.red_window)
        ir_dc = math.fsum(self.ir_window) / len(self.ir_window)
        red_ac = max(self.red_window) - min(self.red_window)
        ir_ac = max(self.ir_window) - min(self.ir_window)
        if red_dc <= 0 or ir_dc <= 0 or red_ac <= 0 or ir_ac <= 0:
            return None
        ratio = (red_ac / red_dc) / (ir_ac / ir_dc)
        estimate = 110 - 25 * ratio
        return estimate if math.isfinite(estimate) else None


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
                "metrics": dict(STATE.latest_metrics),
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
                    record_buffer.extend(packet)
                    while b"\n" in record_buffer:
                        record, _, remainder = record_buffer.partition(b"\n")
                        record_buffer[:] = remainder
                        STATE.add_record(bytes(record))
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
        pulse = math.sin(2 * math.pi * tick / SAMPLE_RATE_HZ)
        red_absorbance = 0.6 + 0.01 * pulse
        ir_absorbance = 0.5 + 0.018 * pulse
        raw = f"{red_absorbance:.6e},{ir_absorbance:.6e}\n".encode("ascii")
        STATE.add_notification(raw)
        STATE.add_record(raw)
        tick += 1
        await asyncio.sleep(1 / SAMPLE_RATE_HZ)


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
