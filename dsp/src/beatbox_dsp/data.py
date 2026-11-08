"""
Windowing, soft labels and patient-wise splitting of the prepared OSASUD arrays
(see prepare_data.py and the design spec).
"""

import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from beatbox_dsp.preprocess import FS, preprocess_patient

DEFAULT_NPZ = Path(__file__).parents[2] / "assets" / "osas.npz"

WINDOW_S = 60
LABEL_THRESHOLD = 0.66  # soft label at or above this counts as an event window for metrics
_LABEL_WEIGHTS = np.hamming(WINDOW_S)

# Per-window vitals features, from the 1 Hz SpO2 / HR values
FEATURE_NAMES = ("spo2_mean", "spo2_min", "spo2_drop", "hr_mean", "hr_range")
N_FEATS = len(FEATURE_NAMES)

# Mostly-missing recordings (>65% of seconds without pleth)
EXCLUDED_PATIENTS = (17, 28)


@dataclass
class Windows:
    x: np.ndarray  # (n, 1, WINDOW_S * FS) float32, preprocessed signal
    y: np.ndarray  # (n,) float32 soft label in [0, 1]
    patient: np.ndarray  # (n,) int16
    feats: np.ndarray  # (n, N_FEATS) float32, see FEATURE_NAMES

    def __len__(self) -> int:
        return len(self.y)


def load(path: Path = DEFAULT_NPZ) -> dict[str, np.ndarray]:
    with np.load(path) as f:
        return {k: f[k] for k in f.files}


def soft_label(event_s: np.ndarray) -> float:
    """Hamming-weighted fraction of the window's seconds that carry any event."""
    return float((_LABEL_WEIGHTS * (event_s > 0)).sum() / _LABEL_WEIGHTS.sum())


def window_features(spo2: np.ndarray, hr: np.ndarray) -> np.ndarray:
    """FEATURE_NAMES from one window's 1 Hz values; missing seconds are ignored (NaN if all missing)."""
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN slices -> NaN, handled by caller
        return np.array([
            np.nanmean(spo2), np.nanmin(spo2), np.nanmax(spo2) - np.nanmin(spo2),
            np.nanmean(hr), np.nanmax(hr) - np.nanmin(hr),
        ], dtype=np.float32)


def make_windows(d: dict[str, np.ndarray], patients: list[int], hop_s: int) -> Windows:
    """Preprocess each patient, then cut WINDOW_S windows every `hop_s` seconds from the
    start of each run of valid (finite) seconds. Windows never cross a gap or a patient.
    Windows whose SpO2 or HR is missing for the whole window are dropped."""
    xs, ys, ps, fs = [], [], [], []
    for p in patients:
        rows = np.flatnonzero(d["patient"] == p)
        sig = preprocess_patient(d["pleth"][rows])
        events, spo2, hr = d["event"][rows], d["spo2"][rows], d["hr"][rows]
        valid = np.isfinite(sig.reshape(-1, FS)).all(axis=1)

        edges = np.diff(np.concatenate([[0], valid.astype(np.int8), [0]]))
        for start, end in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
            for s in range(start, end - WINDOW_S + 1, hop_s):
                f = window_features(spo2[s : s + WINDOW_S], hr[s : s + WINDOW_S])
                if not np.isfinite(f).all():
                    continue
                xs.append(sig[s * FS : (s + WINDOW_S) * FS])
                ys.append(soft_label(events[s : s + WINDOW_S]))
                ps.append(p)
                fs.append(f)

    n = WINDOW_S * FS
    x = np.stack(xs)[:, None, :] if xs else np.empty((0, 1, n), dtype=np.float32)
    feats = np.stack(fs) if fs else np.empty((0, N_FEATS), dtype=np.float32)
    return Windows(x=x.astype(np.float32), y=np.array(ys, dtype=np.float32),
                   patient=np.array(ps, dtype=np.int16), feats=feats)


def split_patients(d: dict[str, np.ndarray], n_val_every: int = 5) -> tuple[list[int], list[int]]:
    """Patient-wise split. Patients are ranked by event rate and every
    `n_val_every`-th one goes to validation, so validation spans mild to severe cases."""
    patients = [int(p) for p in np.unique(d["patient"]) if p not in EXCLUDED_PATIENTS]
    rate = {p: (d["event"][d["patient"] == p] > 0).mean() for p in patients}
    ranked = sorted(patients, key=rate.get)
    val = sorted(ranked[2::n_val_every])
    train = sorted(p for p in patients if p not in val)
    return train, val
