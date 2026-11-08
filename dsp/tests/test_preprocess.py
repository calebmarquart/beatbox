import numpy as np
from scipy.signal import butter

from beatbox_dsp.preprocess import SOS, bandpass, preprocess_patient, zscore_sliding


def _rows(n_s: int, seed: int = 0) -> np.ndarray:
    """n_s seconds of fake 80 Hz pleth: a 1.2 Hz pulse plus noise, as (n_s, 80) rows."""
    rng = np.random.default_rng(seed)
    t = np.arange(n_s * 80) / 80
    x = 100 + 20 * np.sin(2 * np.pi * 1.2 * t) + rng.normal(0, 1, t.size)
    return x.reshape(n_s, 80).astype(np.float32)


def test_sos_matches_scipy_butterworth():
    hp = butter(2, 0.2, "highpass", fs=100, output="sos")
    lp = butter(2, 4.5, "lowpass", fs=100, output="sos")
    np.testing.assert_allclose(SOS, np.vstack([hp, lp]), atol=1e-8)


def test_bandpass_is_causal():
    x = np.random.default_rng(0).standard_normal(1000)
    x2 = x.copy()
    x2[500:] += 5.0
    np.testing.assert_array_equal(bandpass(x)[:500], bandpass(x2)[:500])


def test_zscore_matches_definition():
    x = np.random.default_rng(1).standard_normal(400)
    z = zscore_sliding(x)
    w = x[45:301]
    assert np.isclose(z[300], (x[300] - w.mean()) / (w.std() + 1e-6), rtol=1e-9)
    assert np.isnan(z[:255]).all()
    assert np.isfinite(z[255:]).all()


def test_zscore_flat_signal_is_finite():
    z = zscore_sliding(np.ones(1000))
    assert (z[255:] == 0.0).all()


def test_preprocess_patient_shape_and_settling():
    out = preprocess_patient(_rows(100))
    assert out.shape == (10_000,)
    assert out.dtype == np.float32
    assert np.isnan(out[:1000]).all()
    assert np.isfinite(out[1000:]).all()


def test_preprocess_patient_gap_restarts():
    rows = _rows(200)
    rows[60:65] = np.nan
    out = preprocess_patient(rows)
    assert np.isfinite(out[1000:6000]).all()
    assert np.isnan(out[6000:6500]).all()  # the gap
    assert np.isnan(out[6500:7500]).all()  # settling after the gap
    assert np.isfinite(out[7500:]).all()
    # after the gap the filter/z-score start fresh: identical to processing that segment alone
    np.testing.assert_array_equal(out[7500:], preprocess_patient(rows[65:])[1000:])
