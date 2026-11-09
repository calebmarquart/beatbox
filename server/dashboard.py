"""Stream Beatbox BLE notifications to a small local browser dashboard."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import queue
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic

DEFAULT_DEVICE_NAME = "Beatbox"
DATA_CHARACTERISTIC_UUID = "9f1c0002-4b6a-4c1e-9a52-5d3a7b2e0001"
MAX_HISTORY = 3000
SAMPLE_RATE_HZ = 100
MAX_RECORD_SIZE = 48
APNEA_PROBABILITY_THRESHOLD = 0.26

PAGE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>VespriX</title>
  <style>
    :root { color-scheme: light; font: 15px/1.5 ui-sans-serif, system-ui, sans-serif; background: #F1FAEE; color: #111827; }
    * { box-sizing: border-box; }
    body { margin: 0; background: #F1FAEE; }
    .app-layout { display: grid; grid-template-columns: 210px minmax(0, 1fr); min-height: 100vh; }
    .sidebar { position: sticky; top: 0; height: 100vh; padding: 24px 14px; background: #31587A; color: #fff; }
    .sidebar h2 { margin: 0 10px 20px; border: 0; color: #fff; font-size: 1rem; letter-spacing: .12em; }
    .sidebar nav { display: grid; gap: 8px; }
    .nav-tab { padding: 11px 12px; border: 1px solid transparent; background: transparent; color: #dbe7f1; text-align: left; font: inherit; font-weight: 700; cursor: pointer; }
    .nav-tab:hover, .nav-tab.active { border-color: #457B9D; background: #457B9D; color: #fff; }
    main { width: min(1400px, calc(100% - 32px)); margin: 28px auto 56px; min-width: 0; }
    [hidden] { display: none !important; }
    header { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 20px; padding: 0 0 18px; border-bottom: 3px solid #31587A; }
    h1 { margin: 0; color: #10263c; font-size: 1.65rem; font-weight: 750; letter-spacing: .01em; }
    h2 { margin: 0 0 14px; padding-bottom: 9px; border-bottom: 2px solid #c4ced8; color: #1b334b; font-size: .9rem; font-weight: 750; letter-spacing: .08em; text-transform: uppercase; }
    p { color: #34465a; }
    .status { display: inline-flex; align-items: center; gap: 9px; padding: 8px 12px; border: 2px solid #334155; border-radius: 0; background: #fff; color: #1e293b; font-size: .85rem; font-weight: 700; white-space: nowrap; }
    .header-actions { display: flex; align-items: center; gap: 10px; }
    .download { padding: 8px 12px; border: 2px solid #31587A; border-radius: 0; background: #31587A; color: #fff; font: inherit; font-size: .85rem; font-weight: 700; cursor: pointer; }
    .download:hover { background: #457B9D; }
    .dot { width: 10px; height: 10px; border: 1px solid #334155; border-radius: 0; background: #64748b; }
    .status.connected { border-color: #166534; color: #14532d; background: #f0fdf4; }
    .status.connected .dot { border-color: #14532d; background: #16a34a; }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
    .card { min-width: 0; padding: 18px; border: 2px solid #31587A; border-top: 5px solid #457B9D; border-radius: 0; background: #fff; box-shadow: 3px 3px 0 #b9c5cf; }
    .wide { grid-column: 1 / -1; }
    .metric { color: #10263c; font-size: 2.7rem; font-weight: 750; letter-spacing: -.03em; font-variant-numeric: tabular-nums; }
    .unit { color: #334155; font-size: 1rem; font-weight: 700; }
    .hint { min-height: 24px; margin: 3px 0 0; color: #475569; font-size: .83rem; }
    .threshold-control { display: flex; align-items: center; gap: 10px; margin-top: 6px; color: #334155; font-size: .85rem; font-weight: 700; }
    .threshold-control input { width: min(320px, 55vw); accent-color: #457B9D; }
    .threshold-control output { min-width: 3.5em; color: #1D3557; font-variant-numeric: tabular-nums; }
    .chart-controls { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
    .chart-controls button { padding: 4px 8px; border: 1px solid #64748b; border-radius: 0; background: #f8fafc; color: #1e293b; font: inherit; font-size: .78rem; font-weight: 700; cursor: pointer; }
    .chart-controls button:hover { background: #F1FAEE; }
    canvas { width: 100%; height: 190px; display: block; margin-top: 10px; }
    .empty { padding: 13px; border: 2px dashed #64748b; border-radius: 0; color: #334155; background: #f8fafc; font-size: .9rem; }
    .history-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
    .history-heading h2 { margin-bottom: 4px; }
    .history-heading p { margin: 0; color: #475569; }
    .filter-control { display: inline-flex; align-items: center; gap: 8px; color: #334155; font-size: .85rem; font-weight: 700; }
    .filter-control select { padding: 7px 9px; border: 1px solid #64748b; border-radius: 0; background: #fff; color: #1e293b; font: inherit; }
    .table-wrap { overflow: auto; max-height: calc(100vh - 260px); border: 1px solid #94a3b8; background: #fff; }
    table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
    th, td { padding: 8px 10px; border-bottom: 1px solid #cbd5e1; text-align: right; white-space: nowrap; }
    th { position: sticky; top: 0; background: #F1FAEE; color: #1D3557; }
    th:first-child, td:first-child { text-align: left; }
    .history-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 12px; }
    @media (max-width: 700px) {
      .app-layout { grid-template-columns: 1fr; }
      .sidebar { position: static; height: auto; display: flex; align-items: center; gap: 12px; padding: 10px 14px; }
      .sidebar h2 { margin: 0; }
      .sidebar nav { display: flex; gap: 6px; }
      .nav-tab { padding: 8px 10px; }
      main { margin-top: 18px; }
      .grid { grid-template-columns: 1fr; }
      .wide { grid-column: auto; }
      header { align-items: flex-start; flex-direction: column; }
    }
  </style>
</head>
<body>
<div class="app-layout">
<aside class="sidebar">
  <h2>VespriX</h2>
  <nav aria-label="Dashboard sections">
    <button class="nav-tab active" type="button" data-view="live-view">Live Data</button>
    <button class="nav-tab" type="button" data-view="history-view">History</button>
    <button class="nav-tab" type="button" data-view="events-view">Events</button>
  </nav>
</aside>
<main>
  <header>
    <div><h1>VespriX</h1></div>
    <div class="header-actions"><button id="beep-toggle" class="download" type="button" aria-pressed="false">Heartbeat beep: Off</button><button id="apnea-alarm-toggle" class="download" type="button" aria-pressed="false">Apnea alarm: Off</button><button id="download" class="download" type="button">Download CSV</button><div id="status" class="status"><span class="dot"></span><span id="status-text">Connecting to dashboard…</span></div></div>
  </header>
  <section id="live-view" class="grid">
    <article class="card"><h2>Red value</h2><p id="red-hint" class="hint">Waiting for data</p><canvas id="red-chart" aria-label="Red values over time"></canvas><div class="chart-controls" data-chart="red-chart"><button type="button" data-action="time-in" title="Zoom in horizontally">Time +</button><button type="button" data-action="time-out" title="Zoom out horizontally">Time −</button><button type="button" data-action="reset">Reset</button></div></article>
    <article class="card"><h2>IR value</h2><p id="ir-hint" class="hint">Waiting for data</p><canvas id="ir-chart" aria-label="IR values over time"></canvas><div class="chart-controls" data-chart="ir-chart"><button type="button" data-action="time-in" title="Zoom in horizontally">Time +</button><button type="button" data-action="time-out" title="Zoom out horizontally">Time −</button><button type="button" data-action="reset">Reset</button></div></article>
    <article class="card"><h2>Heart rate</h2><div><span id="heart-rate" class="metric">--</span> <span class="unit">BPM</span></div><p id="hr-hint" class="hint">Waiting for data</p><canvas id="hr-chart" aria-label="Heart rate over time"></canvas><div class="chart-controls" data-chart="hr-chart"><button type="button" data-action="time-in" title="Zoom in horizontally">Time +</button><button type="button" data-action="time-out" title="Zoom out horizontally">Time −</button><button type="button" data-action="reset">Reset</button></div></article>
    <article class="card"><h2>SpO₂</h2><div><span id="spo2-estimate" class="metric">--</span> <span class="unit">%</span></div><p id="spo2-hint" class="hint">Waiting for data</p><canvas id="spo2-chart" aria-label="SpO2 percent over time"></canvas><div class="chart-controls" data-chart="spo2-chart"><button type="button" data-action="time-in" title="Zoom in horizontally">Time +</button><button type="button" data-action="time-out" title="Zoom out horizontally">Time −</button><button type="button" data-action="reset">Reset</button></div></article>
    <article class="card wide"><h2>Sleep apnea probability</h2><div><span id="apnea-probability" class="metric">--</span></div><label class="threshold-control" for="apnea-threshold">Alarm threshold <input id="apnea-threshold" type="range" min="0" max="1" step="0.01" value="0.26"><output id="apnea-threshold-value" for="apnea-threshold">0.26</output></label><p id="apnea-hint" class="hint">Alarm sounds when probability is above the threshold.</p><canvas id="apnea-chart" aria-label="Sleep apnea probability over time"></canvas><div class="chart-controls" data-chart="apnea-chart"><button type="button" data-action="time-in" title="Zoom in horizontally">Time +</button><button type="button" data-action="time-out" title="Zoom out horizontally">Time −</button><button type="button" data-action="reset">Reset</button></div></article>
  </section>
  <section id="history-view" hidden>
    <div class="history-heading">
      <div><h2>Saved sample history</h2></div>
      <label class="filter-control" for="history-range">Time range
        <select id="history-range">
          <option value="300">Last 5 minutes</option>
          <option value="900">Last 15 minutes</option>
          <option value="3600">Last hour</option>
          <option value="21600">Last 6 hours</option>
          <option value="86400" selected>Last 24 hours</option>
          <option value="604800">Last 7 days</option>
          <option value="all">All time</option>
        </select>
      </label>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Timestamp</th><th>Red</th><th>IR</th><th>Heart rate (BPM)</th><th>SpO₂ (%)</th><th>Sleep apnea probability</th></tr></thead>
        <tbody id="history-rows"><tr><td colspan="6">Loading…</td></tr></tbody>
      </table>
    </div>
    <div class="history-footer"><span id="history-count" class="hint"></span><button id="history-older" class="download" type="button" disabled>Load older samples</button></div>
  </section>
  <section id="events-view" hidden>
    <div class="history-heading">
      <div><h2>Events</h2></div>
      <label class="filter-control" for="event-range">Time range
        <select id="event-range">
          <option value="300">Last 5 minutes</option>
          <option value="900">Last 15 minutes</option>
          <option value="3600">Last hour</option>
          <option value="21600">Last 6 hours</option>
          <option value="86400" selected>Last 24 hours</option>
          <option value="604800">Last 7 days</option>
          <option value="all">All time</option>
        </select>
      </label>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Timestamp</th><th>Event</th></tr></thead>
        <tbody id="event-rows"><tr><td colspan="2">Loading…</td></tr></tbody>
      </table>
    </div>
    <div class="history-footer"><span id="event-count" class="hint"></span><button id="event-older" class="download" type="button" disabled>Load older events</button></div>
  </section>
</main>
</div>
<script>
const history = {
  red_value: [],
  ir_value: [],
  heart_rate_bpm: [],
  spo2_percent: [],
  apnea_probability: [],
};
const chartRanges = {
  'red-chart': { windowSeconds: 6 },
  'ir-chart': { windowSeconds: 6 },
  'hr-chart': { windowSeconds: 6 },
  'spo2-chart': { windowSeconds: 6 },
  'apnea-chart': { windowSeconds: 6 },
};
const samples = new Map();
const $ = (id) => document.getElementById(id);
const stamp = (value) => new Date(value).toLocaleTimeString();
const axisTime = (value) => new Date(value).toLocaleTimeString([], {
  hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
});
const formatNumber = (value, digits = 6) => Number(value).toPrecision(digits)
  .replace(/(\.\d*?[1-9])0+(e|$)/, '$1$2')
  .replace(/\.0+(e|$)/, '$1');

function autoRange(values) {
  const dataMin = Math.min(...values);
  const dataMax = Math.max(...values);
  const span = dataMax - dataMin;
  const padding = span > 0 ? span * 0.1 : Math.max(Math.abs(dataMin) * 0.01, 1e-9);
  return { min: dataMin - padding, max: dataMax + padding };
}

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
  const end = Date.parse(points[points.length - 1].time);
  const start = end - range.windowSeconds * 1000;
  const visiblePoints = points.filter((point) => Date.parse(point.time) >= start);
  const { min, max } = autoRange(visiblePoints.map((point) => point.value));
  ctx.fillStyle = '#334155'; ctx.font = '11px system-ui';
  ctx.textAlign = 'right'; ctx.fillText(formatNumber(max, 4), left - 6, top + 4);
  ctx.fillText(formatNumber(min, 4), left - 6, h - bottom + 4);
  ctx.textAlign = 'left'; ctx.fillText(axisTime(start), left, h - 4);
  ctx.textAlign = 'right'; ctx.fillText(axisTime(end), w - right, h - 4);
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

function renderMetric(points, valueId, hintId, chartId, color, missingValue = null) {
  const latest = points[points.length - 1];
  const isMissing = latest && latest.value === missingValue;
  const chartPoints = missingValue === null
    ? points
    : points.filter((point) => point.value !== missingValue);
  if (valueId) {
    $(valueId).textContent = latest && !isMissing
      ? formatNumber(latest.value)
      : '--';
  }
  $(hintId).textContent = latest
    ? `${isMissing ? 'Unavailable' : 'Latest update'} ${stamp(latest.time)}`
    : 'Waiting for data';
  drawChart(chartId, chartPoints, color);
}

function renderMetrics() {
  renderMetric(history.red_value, null, 'red-hint', 'red-chart', '#E63946');
  renderMetric(history.ir_value, null, 'ir-hint', 'ir-chart', '#1D3557');
  renderMetric(history.heart_rate_bpm, 'heart-rate', 'hr-hint', 'hr-chart', '#0f766e', -1);
  renderMetric(history.spo2_percent, 'spo2-estimate', 'spo2-hint', 'spo2-chart', '#457B9D', -1);
  renderMetric(history.apnea_probability, 'apnea-probability', 'apnea-hint', 'apnea-chart', '#E63946');
}

function adjustChartRange(id, action) {
  const range = chartRanges[id];
  if (action === 'time-in' || action === 'time-out') {
    const factor = action === 'time-in' ? 0.8 : 1.25;
    range.windowSeconds = Math.max(0.2, Math.min(30, range.windowSeconds * factor));
  } else if (action === 'reset') {
    range.windowSeconds = 6;
  }
  renderMetrics();
}

function renderSnapshot(snapshot) {
  if (snapshot.apnea_threshold !== undefined) {
    setApneaThreshold(snapshot.apnea_threshold);
  }
  for (const key of Object.keys(history)) history[key] = snapshot.history?.[key] || [];
  const heartRatePoints = history.heart_rate_bpm;
  if (heartRatePoints.length > 0) {
    updateHeartbeatRate(heartRatePoints[heartRatePoints.length - 1].value);
  }
  const apneaPoints = history.apnea_probability;
  if (apneaPoints.length > 0) {
    updateApneaProbability(apneaPoints[apneaPoints.length - 1].value);
  }
  const valueMaps = Object.fromEntries(
    Object.entries(history).map(([key, points]) => [
      key,
      new Map(points.map((point) => [point.time, point.value])),
    ]),
  );
  for (const point of history.red_value) {
    const sample = { timestamp: point.time };
    let complete = true;
    for (const key of Object.keys(history)) {
      const value = valueMaps[key].get(point.time);
      if (value === undefined) {
        complete = false;
        break;
      }
      sample[key] = value;
    }
    if (complete) samples.set(point.time, sample);
  }
  renderMetrics();
}

function downloadSamples() {
  const columns = [
    'red_value', 'ir_value', 'heart_rate_bpm', 'spo2_percent',
    'apnea_probability',
  ];
  const rows = [`timestamp,${columns.join(',')}`];
  const orderedSamples = Array.from(samples.values()).sort((a, b) =>
    a.timestamp.localeCompare(b.timestamp),
  );
  for (const sample of orderedSamples) {
    rows.push(`${sample.timestamp},${columns.map((key) => sample[key]).join(',')}`);
  }
  const blob = new Blob(['\uFEFF', rows.join('\r\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'vesprix-samples.csv';
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function setStatus(text, connected) {
  $('status-text').textContent = text; $('status').classList.toggle('connected', connected);
}

const HISTORY_PAGE_SIZE = 200;
let historyBefore = null;
let historyLoaded = 0;
let historyLoading = false;
let historySince = null;
let historyReloadRequested = false;
const EVENT_PAGE_SIZE = 100;
let APNEA_THRESHOLD = 0.26;
let eventBefore = null;
let eventsLoaded = 0;
let eventsLoading = false;
let eventsSince = null;
let eventsReloadRequested = false;
let heartbeatAudio = null;
let heartbeatBeepEnabled = false;
let heartbeatBeepTimer = null;
let latestHeartRate = null;
let apneaAlarmEnabled = false;
let apneaAlarmTimer = null;
let apneaConditionActive = false;
let latestApneaProbability = null;

function formatHistoryValue(value, digits = 6) {
  return value == null ? '--' : formatNumber(value, digits);
}

function formatInteger(value) {
  return value == null ? '--' : String(value);
}

function appendHistoryRows(rows) {
  const tbody = $('history-rows');
  if (historyLoaded === 0) tbody.replaceChildren();
  for (const row of rows) {
    const tr = document.createElement('tr');
    const cells = [
      new Date(row.timestamp).toLocaleString(),
      formatInteger(row.red_value),
      formatInteger(row.ir_value),
      formatHistoryValue(row.heart_rate_bpm === -1 ? null : row.heart_rate_bpm, 4),
      formatHistoryValue(row.spo2_percent === -1 ? null : row.spo2_percent, 5),
      formatHistoryValue(row.apnea_probability),
    ];
    for (const value of cells) {
      const td = document.createElement('td');
      td.textContent = value;
      tr.append(td);
    }
    tbody.append(tr);
  }
  historyLoaded += rows.length;
  if (rows.length) historyBefore = rows[rows.length - 1].timestamp;
  $('history-count').textContent = `${historyLoaded.toLocaleString()} samples loaded`;
  $('history-older').disabled = rows.length < HISTORY_PAGE_SIZE;
  if (historyLoaded === 0) {
    tbody.innerHTML = '<tr><td colspan="6">No samples saved yet.</td></tr>';
  }
}

async function loadHistory(reset = false) {
  if (historyLoading) {
    if (reset) historyReloadRequested = true;
    return;
  }
  historyLoading = true;
  if (reset) {
    historyBefore = null;
    historyLoaded = 0;
    historySince = getSelectedTimeCutoff('history-range');
    $('history-rows').innerHTML = '<tr><td colspan="6">Loading…</td></tr>';
  }
  const params = new URLSearchParams({ limit: HISTORY_PAGE_SIZE });
  if (historyBefore) params.set('before', historyBefore);
  if (historySince) params.set('since', historySince);
  try {
    const response = await fetch(`/history?${params}`);
    if (!response.ok) throw new Error(`History request failed (${response.status})`);
    const result = await response.json();
    appendHistoryRows(result.samples);
  } catch (error) {
    $('history-rows').innerHTML = `<tr><td colspan="6">Could not load history: ${error.message}</td></tr>`;
  } finally {
    historyLoading = false;
    if (historyReloadRequested) {
      historyReloadRequested = false;
      loadHistory(true);
    }
  }
}

function getSelectedTimeCutoff(selectId) {
  const seconds = Number($(selectId).value);
  if (!Number.isFinite(seconds)) return null;
  return new Date(Date.now() - seconds * 1000).toISOString().replace('Z', '+00:00');
}

function appendEvents(events) {
  const tbody = $('event-rows');
  if (eventsLoaded === 0) tbody.replaceChildren();
  for (const event of events) {
    const tr = document.createElement('tr');
    const timestamp = document.createElement('td');
    timestamp.textContent = new Date(event.timestamp).toLocaleString();
    const name = document.createElement('td');
    name.textContent = event.event_type;
    tr.append(timestamp, name);
    tbody.append(tr);
  }
  eventsLoaded += events.length;
  if (events.length) eventBefore = events[events.length - 1].id;
  $('event-count').textContent = eventsLoaded
    ? `${eventsLoaded.toLocaleString()} events loaded`
    : '';
  $('event-older').disabled = events.length < EVENT_PAGE_SIZE;
  if (eventsLoaded === 0) {
    tbody.innerHTML = '<tr><td colspan="2">No Events</td></tr>';
  }
}

async function loadEvents(reset = false) {
  if (eventsLoading) {
    if (reset) eventsReloadRequested = true;
    return;
  }
  eventsLoading = true;
  if (reset) {
    eventBefore = null;
    eventsLoaded = 0;
    eventsSince = getSelectedTimeCutoff('event-range');
    $('event-rows').innerHTML = '<tr><td colspan="2">Loading…</td></tr>';
  }
  const params = new URLSearchParams({ limit: EVENT_PAGE_SIZE });
  if (eventBefore !== null) params.set('before_id', eventBefore);
  if (eventsSince) params.set('since', eventsSince);
  try {
    const response = await fetch(`/event-history?${params}`);
    if (!response.ok) throw new Error(`Event request failed (${response.status})`);
    const result = await response.json();
    appendEvents(result.events);
  } catch (error) {
    $('event-rows').innerHTML = `<tr><td colspan="2">Could not load events: ${error.message}</td></tr>`;
  } finally {
    eventsLoading = false;
    if (eventsReloadRequested) {
      eventsReloadRequested = false;
      loadEvents(true);
    }
  }
}

function playHeartbeatBeep() {
  if (!heartbeatAudio || heartbeatAudio.state !== 'running') return;
  const oscillator = heartbeatAudio.createOscillator();
  const gain = heartbeatAudio.createGain();
  const now = heartbeatAudio.currentTime;
  oscillator.type = 'square';
  oscillator.frequency.setValueAtTime(366, now);
  gain.gain.setValueAtTime(0.0001, now);
  gain.gain.exponentialRampToValueAtTime(0.12, now + 0.003);
  gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.14);
  oscillator.connect(gain);
  gain.connect(heartbeatAudio.destination);
  oscillator.start(now);
  oscillator.stop(now + 0.15);
}

function scheduleHeartbeatBeep() {
  if (!heartbeatBeepEnabled || latestHeartRate == null
    || latestHeartRate < 30 || latestHeartRate > 240
    || heartbeatBeepTimer !== null) return;
  heartbeatBeepTimer = setTimeout(() => {
    heartbeatBeepTimer = null;
    if (!heartbeatBeepEnabled) return;
    playHeartbeatBeep();
    scheduleHeartbeatBeep();
  }, 60000 / latestHeartRate);
}

function updateHeartbeatRate(value) {
  const parsed = Number(value);
  latestHeartRate = value == null || !Number.isFinite(parsed) ? null : parsed;
  if (!heartbeatBeepEnabled) return;
  if (latestHeartRate == null || latestHeartRate < 30 || latestHeartRate > 240) {
    if (heartbeatBeepTimer !== null) clearTimeout(heartbeatBeepTimer);
    heartbeatBeepTimer = null;
    return;
  }
  scheduleHeartbeatBeep();
}

async function toggleHeartbeatBeep() {
  heartbeatBeepEnabled = !heartbeatBeepEnabled;
  const button = $('beep-toggle');
  button.setAttribute('aria-pressed', String(heartbeatBeepEnabled));
  button.textContent = `Heartbeat beep: ${heartbeatBeepEnabled ? 'On' : 'Off'}`;
  if (!heartbeatBeepEnabled) {
    if (heartbeatBeepTimer !== null) clearTimeout(heartbeatBeepTimer);
    heartbeatBeepTimer = null;
    return;
  }
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) {
    heartbeatBeepEnabled = false;
    button.setAttribute('aria-pressed', 'false');
    button.textContent = 'Heartbeat beep unavailable';
    return;
  }
  if (!heartbeatAudio) heartbeatAudio = new AudioContextClass();
  await heartbeatAudio.resume();
  if (latestHeartRate != null && latestHeartRate >= 30 && latestHeartRate <= 240) {
    playHeartbeatBeep();
    scheduleHeartbeatBeep();
  }
}

function playApneaAlarmBeep() {
  if (!heartbeatAudio || heartbeatAudio.state !== 'running') return;
  const oscillator = heartbeatAudio.createOscillator();
  const gain = heartbeatAudio.createGain();
  const now = heartbeatAudio.currentTime;
  oscillator.type = 'square';
  oscillator.frequency.setValueAtTime(880, now);
  gain.gain.setValueAtTime(0.0001, now);
  gain.gain.exponentialRampToValueAtTime(0.16, now + 0.003);
  gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.22);
  oscillator.connect(gain);
  gain.connect(heartbeatAudio.destination);
  oscillator.start(now);
  oscillator.stop(now + 0.23);
}

function startApneaAlarm() {
  if (!apneaAlarmEnabled || !apneaConditionActive || apneaAlarmTimer !== null) return;
  playApneaAlarmBeep();
  apneaAlarmTimer = setInterval(playApneaAlarmBeep, 650);
}

function stopApneaAlarm() {
  if (apneaAlarmTimer !== null) clearInterval(apneaAlarmTimer);
  apneaAlarmTimer = null;
}

function updateApneaProbability(value) {
  const parsed = value == null ? NaN : Number(value);
  latestApneaProbability = Number.isFinite(parsed) ? parsed : null;
  apneaConditionActive = latestApneaProbability !== null
    && latestApneaProbability > APNEA_THRESHOLD;
  $('apnea-hint').textContent = apneaConditionActive
    ? `ALERT: probability over ${APNEA_THRESHOLD}`
    : `Alarm sounds when probability is above ${APNEA_THRESHOLD}.`;
  if (apneaConditionActive) startApneaAlarm();
  else stopApneaAlarm();
}

function setApneaThreshold(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return;
  APNEA_THRESHOLD = Math.max(0, Math.min(1, parsed));
  $('apnea-threshold').value = String(APNEA_THRESHOLD);
  $('apnea-threshold-value').textContent = APNEA_THRESHOLD.toFixed(2);
  updateApneaProbability(latestApneaProbability);
}

async function saveApneaThreshold() {
  try {
    const response = await fetch('/settings/apnea-threshold', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ threshold: APNEA_THRESHOLD }),
    });
    if (!response.ok) throw new Error(`Save failed (${response.status})`);
  } catch (error) {
    $('apnea-hint').textContent = `Could not save alarm threshold: ${error.message}`;
  }
}

async function toggleApneaAlarm() {
  apneaAlarmEnabled = !apneaAlarmEnabled;
  const button = $('apnea-alarm-toggle');
  button.setAttribute('aria-pressed', String(apneaAlarmEnabled));
  button.textContent = `Apnea alarm: ${apneaAlarmEnabled ? 'On' : 'Off'}`;
  if (!apneaAlarmEnabled) {
    stopApneaAlarm();
    return;
  }
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) {
    apneaAlarmEnabled = false;
    button.setAttribute('aria-pressed', 'false');
    button.textContent = 'Apnea alarm unavailable';
    return;
  }
  if (!heartbeatAudio) heartbeatAudio = new AudioContextClass();
  await heartbeatAudio.resume();
  startApneaAlarm();
}

document.querySelectorAll('.nav-tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.nav-tab').forEach((item) => item.classList.remove('active'));
    tab.classList.add('active');
    for (const viewId of ['live-view', 'history-view', 'events-view']) {
      $(viewId).hidden = viewId !== tab.dataset.view;
    }
    if (tab.dataset.view === 'history-view') loadHistory(true);
    else if (tab.dataset.view === 'events-view') loadEvents(true);
    else renderMetrics();
  });
});
$('beep-toggle').addEventListener('click', toggleHeartbeatBeep);
$('apnea-alarm-toggle').addEventListener('click', toggleApneaAlarm);
$('history-older').addEventListener('click', () => loadHistory(false));
$('event-older').addEventListener('click', () => loadEvents(false));
$('history-range').addEventListener('change', () => loadHistory(true));
$('event-range').addEventListener('change', () => loadEvents(true));
$('apnea-threshold').addEventListener('input', (event) => {
  setApneaThreshold(event.currentTarget.value);
});
$('apnea-threshold').addEventListener('change', saveApneaThreshold);

const source = new EventSource('/events');
source.onopen = () => setStatus('Connected', true);
source.onerror = () => setStatus('Reconnecting to dashboard…', false);
source.addEventListener('snapshot', (event) => renderSnapshot(JSON.parse(event.data)));
source.addEventListener('settings', (event) => {
  const data = JSON.parse(event.data);
  setApneaThreshold(data.apnea_threshold);
});
source.addEventListener('ble_status', (event) => {
  const data = JSON.parse(event.data);
  setStatus(data.connected ? `${data.device} connected` : data.message, data.connected);
});
source.addEventListener('measurement', (event) => {
  const data = JSON.parse(event.data);
  updateHeartbeatRate(data.heart_rate_bpm);
  updateApneaProbability(data.apnea_probability);
  samples.set(data.time, {
    timestamp: data.time,
    red_value: data.red_value,
    ir_value: data.ir_value,
    heart_rate_bpm: data.heart_rate_bpm,
    spo2_percent: data.spo2_percent,
    apnea_probability: data.apnea_probability,
  });
  for (const key of Object.keys(history)) if (data[key] !== undefined) {
    history[key].push({ time: data.time, value: data[key] });
    history[key] = history[key].slice(-3000);
  }
  renderMetrics();
});
source.addEventListener('apnea_event', () => {
  if (!$('events-view').hidden) loadEvents(true);
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


def normalize_since(value: str | None) -> str | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("since timestamp must include a timezone")
    return parsed.astimezone(UTC).isoformat(timespec="milliseconds")


class SampleHistoryDatabase:
    def __init__(self, path: Path | None = None) -> None:
        database_path = path or Path(__file__).with_name("beatbox_history.sqlite3")
        self.lock = threading.Lock()
        self.connection = sqlite3.connect(database_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        with self.lock:
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA synchronous=NORMAL")
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS samples (
                    timestamp TEXT PRIMARY KEY,
                    red_absorbance REAL NOT NULL,
                    ir_absorbance REAL NOT NULL,
                    heart_rate_bpm REAL,
                    spo2_estimate_percent REAL,
                    ratio REAL,
                    apnea_probability REAL
                )
                """
            )
            sample_columns = {
                row["name"]
                for row in self.connection.execute("PRAGMA table_info(samples)")
            }
            if "ratio" not in sample_columns:
                self.connection.execute("ALTER TABLE samples ADD COLUMN ratio REAL")
            if "apnea_probability" not in sample_columns:
                self.connection.execute(
                    "ALTER TABLE samples ADD COLUMN apnea_probability REAL"
                )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL
                )
                """
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS events_timestamp_idx ON events(timestamp)"
            )
            self.connection.commit()

    def insert(self, sample: dict[str, Any]) -> None:
        with self.lock:
            self.connection.execute(
                """
                INSERT OR REPLACE INTO samples (
                    timestamp,
                    red_absorbance,
                    ir_absorbance,
                    heart_rate_bpm,
                    spo2_estimate_percent,
                    ratio,
                    apnea_probability
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sample["time"],
                    sample["red_value"],
                    sample["ir_value"],
                    sample.get("heart_rate_bpm"),
                    sample.get("spo2_percent"),
                    sample["ratio"],
                    sample["apnea_probability"],
                ),
            )
            self.connection.commit()

    def page(
        self,
        limit: int,
        before: str | None = None,
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        query = """SELECT timestamp,
            red_absorbance AS red_value,
            ir_absorbance AS ir_value,
            heart_rate_bpm,
            spo2_estimate_percent AS spo2_percent,
            ratio,
            apnea_probability
            FROM samples"""
        values: list[Any] = []
        conditions: list[str] = []
        if since is not None:
            conditions.append("timestamp >= ?")
            values.append(since)
        if before is not None:
            conditions.append("timestamp < ?")
            values.append(before)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY timestamp DESC LIMIT ?"
        values.append(limit)
        with self.lock:
            rows = self.connection.execute(query, values).fetchall()
        return [dict(row) for row in rows]

    def insert_event(self, timestamp: str, event_type: str) -> None:
        with self.lock:
            self.connection.execute(
                "INSERT INTO events (timestamp, event_type) VALUES (?, ?)",
                (timestamp, event_type),
            )
            self.connection.commit()

    def event_page(
        self,
        limit: int,
        before_id: int | None = None,
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT id, timestamp, event_type FROM events"
        values: list[Any] = []
        conditions: list[str] = []
        if since is not None:
            conditions.append("timestamp >= ?")
            values.append(since)
        if before_id is not None:
            conditions.append("id < ?")
            values.append(before_id)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY id DESC LIMIT ?"
        values.append(limit)
        with self.lock:
            rows = self.connection.execute(query, values).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        with self.lock:
            self.connection.close()


HISTORY_DB = SampleHistoryDatabase()


class DashboardState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.subscribers: set[queue.Queue[tuple[str, dict[str, Any]]]] = set()
        self.history: dict[str, list[dict[str, Any]]] = {
            "red_value": [],
            "ir_value": [],
            "heart_rate_bpm": [],
            "spo2_percent": [],
            "ratio": [],
            "apnea_probability": [],
        }
        self.last_sample_time: datetime | None = None
        self.apnea_active = False
        self.apnea_threshold = APNEA_PROBABILITY_THRESHOLD

    def set_apnea_threshold(self, threshold: float) -> None:
        with self.lock:
            self.apnea_threshold = threshold
        self.publish("settings", {"apnea_threshold": threshold})

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
                "apnea_threshold": self.apnea_threshold,
            }

    def add_record(self, raw: bytes) -> None:
        try:
            fields = raw.decode("ascii").strip().split(",")
            if len(fields) != 6:
                return
            red_value = int(fields[0].strip())
            ir_value = int(fields[1].strip())
            heart_rate_bpm = float(fields[2].strip())
            spo2_percent = float(fields[3].strip())
            ratio = float(fields[4].strip())
            apnea_probability = float(fields[5].strip())
        except (UnicodeDecodeError, ValueError):
            return
        if (
            not all(
                math.isfinite(value)
                for value in (
                    heart_rate_bpm,
                    spo2_percent,
                    ratio,
                    apnea_probability,
                )
            )
            or not -1 <= ratio <= 1
            or (apnea_probability != -1 and not 0 <= apnea_probability <= 1)
        ):
            return
        with self.lock:
            if self.last_sample_time is None:
                sample_datetime = datetime.now(UTC)
            else:
                sample_datetime = self.last_sample_time + timedelta(
                    seconds=1 / SAMPLE_RATE_HZ
                )
            self.last_sample_time = sample_datetime
            sample_time = sample_datetime.isoformat(timespec="milliseconds")
            measurement: dict[str, Any] = {
                "time": sample_time,
                "red_value": red_value,
                "ir_value": ir_value,
                "heart_rate_bpm": heart_rate_bpm,
                "spo2_percent": spo2_percent,
                "ratio": ratio,
                "apnea_probability": apnea_probability,
            }
            apnea_threshold = self.apnea_threshold
            apnea_detected = apnea_probability > apnea_threshold
            record_apnea_event = apnea_detected and not self.apnea_active
            self.apnea_active = apnea_detected
            for key in self.history:
                self.history[key].append(
                    {"time": sample_time, "value": measurement[key]}
                )
                del self.history[key][:-MAX_HISTORY]
        # Debug raw BLE record bytes and their length when needed:
        print(f"Received {len(raw)} bytes: {raw!r}", flush=True)
        print(
            f"{sample_time} red={red_value} IR={ir_value} "
            f"HR={heart_rate_bpm:g} BPM SpO2={spo2_percent:g}% "
            f"apnea_probability={apnea_probability:g}",
            flush=True,
        )
        try:
            HISTORY_DB.insert(measurement)
        except sqlite3.Error as exc:
            print(f"[history] Could not save sample: {exc}", flush=True)
        if record_apnea_event:
            event_type = (
                f"Sleep apnea probability exceeded {apnea_threshold:.2f} "
                f"({apnea_probability:.3f})"
            )
            try:
                HISTORY_DB.insert_event(sample_time, event_type)
            except sqlite3.Error as exc:
                print(f"[history] Could not save apnea event: {exc}", flush=True)
            self.publish(
                "apnea_event",
                {"time": sample_time, "probability": apnea_probability},
            )
        self.publish("measurement", measurement)


STATE = DashboardState()


class DashboardHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/settings/apnea-threshold":
            self.send_error(404)
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400, "Invalid request length")
            return
        if content_length <= 0 or content_length > 1024:
            self.send_error(400, "Invalid request length")
            return
        try:
            payload = json.loads(self.rfile.read(content_length))
            threshold = float(payload["threshold"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            self.send_error(400, "Invalid apnea threshold")
            return
        if not math.isfinite(threshold) or not 0 <= threshold <= 1:
            self.send_error(400, "Apnea threshold must be between 0 and 1")
            return

        STATE.set_apnea_threshold(threshold)
        body = json.dumps({"apnea_threshold": threshold}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed_path = urlsplit(self.path)
        if parsed_path.path == "/":
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed_path.path == "/event-history":
            query = parse_qs(parsed_path.query)
            try:
                requested_limit = int(query.get("limit", ["100"])[0])
            except ValueError:
                requested_limit = 100
            limit = max(1, min(requested_limit, 500))
            try:
                before_id = int(query["before_id"][0]) if "before_id" in query else None
            except ValueError:
                before_id = None
            try:
                since = normalize_since(query.get("since", [None])[0])
            except ValueError:
                self.send_error(400, "Invalid since timestamp")
                return
            try:
                body = json.dumps(
                    {"events": HISTORY_DB.event_page(limit, before_id, since)},
                    separators=(",", ":"),
                ).encode("utf-8")
            except sqlite3.Error as exc:
                self.send_error(500, f"Could not read saved events: {exc}")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed_path.path == "/history":
            query = parse_qs(parsed_path.query)
            try:
                requested_limit = int(query.get("limit", ["200"])[0])
            except ValueError:
                requested_limit = 200
            limit = max(1, min(requested_limit, 500))
            before = query.get("before", [None])[0]
            try:
                since = normalize_since(query.get("since", [None])[0])
            except ValueError:
                self.send_error(400, "Invalid since timestamp")
                return
            try:
                body = json.dumps(
                    {"samples": HISTORY_DB.page(limit, before, since)},
                    separators=(",", ":"),
                ).encode("utf-8")
            except sqlite3.Error as exc:
                self.send_error(500, f"Could not read saved history: {exc}")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed_path.path == "/events":
            self._stream_events()
            return
        self.send_error(404)

    def _stream_events(self) -> None:
        subscriber: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue(maxsize=128)
        with STATE.lock:
            STATE.subscribers.add(subscriber)
            snapshot = {
                "history": {key: list(points) for key, points in STATE.history.items()},
                "apnea_threshold": STATE.apnea_threshold,
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
                    record_buffer.extend(packet)
                    while b"\n" in record_buffer:
                        record, _, remainder = record_buffer.partition(b"\n")
                        record_buffer[:] = remainder
                        STATE.add_record(bytes(record).strip())
                    if len(record_buffer) > MAX_RECORD_SIZE:
                        record_buffer.clear()

                await client.start_notify(characteristic_uuid, on_notification)
                STATE.publish("ble_status", {"connected": True, "device": name})
                print(f"Connected; forwarding samples to the dashboard for {name}.")
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
        red_value = 13_771 + round(500 * pulse)
        ir_value = 17_891 + round(600 * pulse)
        heart_rate_bpm = 72 + 3 * pulse
        spo2_percent = 97.2 + 0.4 * pulse
        ratio = 0.25 * pulse
        apnea_probability = (
            0.36 if tick % (15 * SAMPLE_RATE_HZ) < 3 * SAMPLE_RATE_HZ else 0.08
        )
        raw = (
            f"{red_value},{ir_value},{heart_rate_bpm:.2f},"
            f"{spo2_percent:.2f},{ratio:.4f},{apnea_probability:.2f}\n"
        ).encode("ascii")
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
        HISTORY_DB.close()


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
