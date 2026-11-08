"""
Windowing, soft labels and patient-wise splitting of the prepared OSASUD arrays
(see prepare_data.py and the design spec).
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from beatbox_dsp.preprocess import FS, preprocess_patient

DEFAULT_NPZ = Path(__file__).parents[2] / "assets" / "osas.npz"

WINDOW_S = 30
LABEL_THRESHOLD = 0.66  # soft label at or above this counts as an event window for metrics
_LABEL_WEIGHTS = np.hamming(WINDOW_S)

# Mostly-missing recordings (>65% of seconds without pleth)
EXCLUDED_PATIENTS = (17, 28)


@dataclass
class Windows:
    x: np.ndarray  # (n, 1, WINDOW_S * FS) float32, preprocessed signal
    y: np.ndarray  # (n,) float32 soft label in [0, 1]
    patient: np.ndarray  # (n,) int16

    def __len__(self) -> int:
        return len(self.y)


def load(path: Path = DEFAULT_NPZ) -> dict[str, np.ndarray]:
    with np.load(path) as f:
        return {k: f[k] for k in f.files}


def soft_label(event_s: np.ndarray) -> float:
    """Hamming-weighted fraction of the window's seconds that carry any event."""
    return float((_LABEL_WEIGHTS * (event_s > 0)).sum() / _LABEL_WEIGHTS.sum())


def make_windows(d: dict[str, np.ndarray], patients: list[int], hop_s: int) -> Windows:
    """Preprocess each patient, then cut WINDOW_S windows every `hop_s` seconds from the
    start of each run of valid (finite) seconds. Windows never cross a gap or a patient."""
    xs, ys, ps = [], [], []
    for p in patients:
        rows = np.flatnonzero(d["patient"] == p)
        sig = preprocess_patient(d["pleth"][rows])
        events = d["event"][rows]
        valid = np.isfinite(sig.reshape(-1, FS)).all(axis=1)

        edges = np.diff(np.concatenate([[0], valid.astype(np.int8), [0]]))
        for start, end in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
            for s in range(start, end - WINDOW_S + 1, hop_s):
                xs.append(sig[s * FS : (s + WINDOW_S) * FS])
                ys.append(soft_label(events[s : s + WINDOW_S]))
                ps.append(p)

    n = WINDOW_S * FS
    x = np.stack(xs)[:, None, :] if xs else np.empty((0, 1, n), dtype=np.float32)
    return Windows(x=x.astype(np.float32), y=np.array(ys, dtype=np.float32), patient=np.array(ps, dtype=np.int16))


def split_patients(d: dict[str, np.ndarray], n_val_every: int = 5) -> tuple[list[int], list[int]]:
    """Patient-wise split. Patients are ranked by event rate and every
    `n_val_every`-th one goes to validation, so validation spans mild to severe cases."""
    patients = [int(p) for p in np.unique(d["patient"]) if p not in EXCLUDED_PATIENTS]
    rate = {p: (d["event"][d["patient"] == p] > 0).mean() for p in patients}
    ranked = sorted(patients, key=rate.get)
    val = sorted(ranked[2::n_val_every])
    train = sorted(p for p in patients if p not in val)
    return train, val
