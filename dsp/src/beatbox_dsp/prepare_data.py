"""
One-off conversion of the OSASUD pickle into compact numpy arrays.

Loading the pickle takes ~80 s and lots of RAM; the .npz this writes loads in seconds.

    uv run python -m beatbox_dsp.prepare_data [pickle] [out.npz]

Output arrays (one row per second, rows grouped by patient in time order):
    patient  (N,)     int16    patient id
    pleth    (N, 80)  float32  PPG waveform, 80 Hz; NaN where missing
    spo2     (N,)     float32  SpO2 %, NaN where missing
    hr       (N,)     float32  heart rate bpm, NaN where missing
    event    (N,)     int8     index into EVENTS
"""

import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd

EVENTS = ["NONE", "HYPOPNEA", "APNEA-OBSTRUCTIVE", "APNEA-CENTRAL", "APNEA-MIXED"]
FS_PLETH = 80

DEFAULT_IN = Path(__file__).parents[2] / "assets" / "dataset_OSAS(1).pickle"
DEFAULT_OUT = Path(__file__).parents[2] / "assets" / "osas.npz"


def convert(df: pd.DataFrame) -> dict[str, np.ndarray]:
    df = df.assign(patient=df["patient"].astype(int))
    df = df.sort_values(["patient", "timestamp_datetime"], kind="stable")

    # Every second must follow the previous one, otherwise windows would span gaps
    step = df.groupby("patient")["timestamp_datetime"].diff().dt.total_seconds()
    if not (step.dropna() == 1.0).all():
        raise ValueError("timestamps are not contiguous 1 s steps within each patient")

    unknown = set(df["event"].unique()) - set(EVENTS)
    if unknown:
        raise ValueError(f"unknown event labels: {unknown}")

    pleth = np.stack(df["signal_pleth"].to_numpy()).astype(np.float32)
    if pleth.shape[1] != FS_PLETH:
        raise ValueError(f"expected {FS_PLETH} pleth samples per row, got {pleth.shape[1]}")

    return {
        "patient": df["patient"].to_numpy(np.int16),
        "pleth": pleth,
        "spo2": df["SpO2(%)"].to_numpy(np.float32),
        "hr": df["HR(bpm)"].to_numpy(np.float32),
        "event": df["event"].map(EVENTS.index).to_numpy(np.int8),
        "event_names": np.array(EVENTS),
    }


def summarize(d: dict[str, np.ndarray]) -> pd.DataFrame:
    pleth_missing = np.isnan(d["pleth"]).all(axis=1)
    df = pd.DataFrame({
        "patient": d["patient"],
        "event": d["event"] > 0,
        "pleth_missing": pleth_missing,
        "spo2_missing": np.isnan(d["spo2"]),
    })
    g = df.groupby("patient")
    out = pd.DataFrame({
        "hours": g.size() / 3600,
        "event_%": g["event"].mean() * 100,
        "pleth_missing_%": g["pleth_missing"].mean() * 100,
        "spo2_missing_%": g["spo2_missing"].mean() * 100,
    })
    return out.round(1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pickle", nargs="?", type=Path, default=DEFAULT_IN)
    ap.add_argument("out", nargs="?", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    t0 = time.time()
    print(f"loading {args.pickle} ...")
    df = pd.read_pickle(args.pickle)
    print(f"loaded {len(df):,} rows in {time.time() - t0:.0f} s")

    d = convert(df)
    del df

    np.savez(args.out, **d)
    print(f"wrote {args.out} ({args.out.stat().st_size / 1e6:.0f} MB)\n")

    s = summarize(d)
    with pd.option_context("display.max_rows", None):
        print(s)
    print(f"\npatients {len(s)}, hours {s['hours'].sum():.0f}")
    counts = np.bincount(d["event"], minlength=len(EVENTS))
    for name, n in zip(EVENTS, counts):
        print(f"  {name:<18} {n:>8,} s  ({100 * n / len(d['event']):.1f}%)")
    print(f"  pleth rows all-NaN: {np.isnan(d['pleth']).all(axis=1).mean() * 100:.1f}%")
    print(f"  pleth rows part-NaN: {(np.isnan(d['pleth']).any(axis=1) & ~np.isnan(d['pleth']).all(axis=1)).mean() * 100:.1f}%")


if __name__ == "__main__":
    main()
