"""
Signal front end shared by training and the device (see the design spec).

    pleth @ 80 Hz -> resample to 100 Hz -> causal Butterworth band-pass -> sliding 256-sample z-score

The device runs the same chain on MAX30102 absorbance at 100 Hz (no resampling).
Each gap-free segment is processed from a fresh start; its first SETTLE_S seconds
are marked missing while the filter and z-score settle.
"""

import numpy as np
from scipy.signal import resample_poly, sosfilt

FS = 100  # model / device sample rate
FS_DATASET = 80
SETTLE_S = 10
ZSCORE_N = 256
ZSCORE_EPS = 1e-6

# Device coefficients, CMSIS biquad order per stage: b0, b1, b2, a1, a2 (feedback negated)
CMSIS_COEFFS = np.array([
    # stage 1: high-pass, fc = 0.2 Hz
    0.991153595, -1.98230719, 0.991153595, 1.98222893, -0.982385451,
    # stage 2: low-pass, fc = 4.5 Hz
    0.0165819317, 0.0331638633, 0.0165819317, 1.60413018, -0.670457906,
])

# SciPy second-order sections: [b0, b1, b2, 1, -a1, -a2] per stage
SOS = np.array([[b0, b1, b2, 1.0, -a1, -a2] for b0, b1, b2, a1, a2 in CMSIS_COEFFS.reshape(2, 5)])


def bandpass(x: np.ndarray) -> np.ndarray:
    """Causal band-pass from zero initial state, as on the device."""
    return sosfilt(SOS, x)


def zscore_sliding(x: np.ndarray, n: int = ZSCORE_N, eps: float = ZSCORE_EPS) -> np.ndarray:
    """z[i] = (x[i] - mean(x[i-n+1..i])) / (std(x[i-n+1..i]) + eps), population std.
    The first n-1 outputs are NaN (not enough history)."""
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    win = np.lib.stride_tricks.sliding_window_view(x, n)
    out[n - 1:] = (x[n - 1:] - win.mean(axis=1)) / (win.std(axis=1) + eps)
    return out


def preprocess_patient(pleth: np.ndarray) -> np.ndarray:
    """(n_s, 80) pleth rows (NaN rows = missing seconds) -> (n_s*100,) float32 at 100 Hz.
    Gaps and the first SETTLE_S seconds of every gap-free segment are NaN."""
    n_s = len(pleth)
    out = np.full(n_s * FS, np.nan, dtype=np.float32)
    valid = ~np.isnan(pleth).any(axis=1)

    # runs of consecutive valid seconds: [start, end)
    edges = np.diff(np.concatenate([[0], valid.astype(np.int8), [0]]))
    for start, end in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
        x = resample_poly(pleth[start:end].astype(np.float64).ravel(), FS, FS_DATASET)
        z = zscore_sliding(bandpass(x))
        z[: SETTLE_S * FS] = np.nan
        out[start * FS : end * FS] = z
    return out
