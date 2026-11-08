import numpy as np
import pytest
import torch

from beatbox_dsp.model import TinyCNN
from beatbox_dsp.preprocess import bandpass, zscore_sliding
from beatbox_dsp.stream import StreamingFrontEnd, StreamingModel, stream_window


def _torch_logit(m: TinyCNN, x: np.ndarray) -> float:
    with torch.no_grad():
        return m(torch.tensor(x, dtype=torch.float32)[None, None]).item()


def test_frontend_matches_batch():
    x = np.random.default_rng(0).standard_normal(2000)
    fe = StreamingFrontEnd()
    got = np.array([fe.step(v) for v in x])
    expected = zscore_sliding(bandpass(x))
    assert np.array_equal(np.isnan(got), np.isnan(expected))
    np.testing.assert_allclose(got[255:], expected[255:], atol=1e-6)


def test_stream_matches_torch_random_weights():
    torch.manual_seed(0)
    m = TinyCNN().eval()
    x = np.random.default_rng(0).standard_normal(3000)
    assert stream_window(StreamingModel(m), x) == pytest.approx(_torch_logit(m, x), abs=1e-4)


def test_stream_resets_between_windows():
    torch.manual_seed(1)
    m = TinyCNN().eval()
    rng = np.random.default_rng(1)
    x1, x2 = rng.standard_normal(3000), rng.standard_normal(3000)
    sm = StreamingModel(m)
    stream_window(sm, x1)
    assert stream_window(sm, x2) == pytest.approx(stream_window(StreamingModel(m), x2), abs=1e-12)
