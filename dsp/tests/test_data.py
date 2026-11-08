import numpy as np
import pytest

from beatbox_dsp.data import make_windows, soft_label


def _dataset(n_s: int, gap: tuple[int, int] | None = None, event: tuple[int, int] | None = None) -> dict:
    """One fake patient (id 1): n_s seconds of 80 Hz pulse, optional NaN gap / event seconds."""
    rng = np.random.default_rng(0)
    t = np.arange(n_s * 80) / 80
    pleth = (100 + 20 * np.sin(2 * np.pi * 1.2 * t) + rng.normal(0, 1, t.size)).reshape(n_s, 80)
    if gap:
        pleth[gap[0]:gap[1]] = np.nan
    ev = np.zeros(n_s, dtype=np.int8)
    if event:
        ev[event[0]:event[1]] = 2
    return {"patient": np.ones(n_s, dtype=np.int16), "pleth": pleth.astype(np.float32), "event": ev}


def test_soft_label_values():
    assert soft_label(np.zeros(30)) == 0.0
    assert soft_label(np.ones(30)) == pytest.approx(1.0)
    centre = np.zeros(30)
    centre[10:20] = 1
    edge = np.zeros(30)
    edge[:10] = 1
    assert soft_label(centre) > 0.5 > soft_label(edge) > 0.0


def test_windows_shape_and_hop():
    d = _dataset(100)
    w15 = make_windows(d, [1], hop_s=15)
    assert w15.x.shape == (5, 1, 3000)  # valid seconds 10..99, starts 10,25,40,55,70
    assert w15.x.dtype == np.float32
    assert np.isfinite(w15.x).all()
    assert len(make_windows(d, [1], hop_s=30)) == 3  # starts 10,40,70


def test_no_window_crosses_gap():
    d = _dataset(100, gap=(50, 55))
    w = make_windows(d, [1], hop_s=15)
    # valid runs after settling: [10, 50) -> starts 10 only (25+30 > 50); [65, 100) -> start 65
    assert len(w) == 2
    assert np.isfinite(w.x).all()


def test_short_segment_yields_no_windows():
    assert len(make_windows(_dataset(35), [1], hop_s=15)) == 0


def test_label_uses_window_seconds():
    d = _dataset(100, event=(25, 35))
    w = make_windows(d, [1], hop_s=30)  # windows at 10, 40, 70
    assert w.y[0] == pytest.approx(soft_label(d["event"][10:40]))
    assert w.y[1] == pytest.approx(soft_label(d["event"][40:70]))
    assert w.y[0] > 0.0 and w.y[1] == 0.0
