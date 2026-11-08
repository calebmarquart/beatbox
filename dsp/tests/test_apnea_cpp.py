"""Compiles the firmware's Modules/apnea/apnea.cpp on the host and checks it against the Python reference."""

import shutil

import numpy as np
import pytest
import torch

from beatbox_dsp.export import (
    build_and_run_host_check,
    write_test_vectors,
    write_weights,
)
from beatbox_dsp.model import TinyCNN

pytestmark = pytest.mark.skipif(shutil.which("g++") is None, reason="g++ not available")


def test_cpp_matches_reference(tmp_path):
    torch.manual_seed(0)
    model = TinyCNN().eval()
    model.set_feature_norm(torch.tensor([96.0, 93.0, 2.0, 65.0, 8.0]), torch.tensor([2.0, 3.0, 2.0, 10.0, 5.0]))
    rng = np.random.default_rng(0)
    x = rng.standard_normal((3, 6000)).astype(np.float32)
    feats = np.array([[97, 96, 1, 60, 4], [93, 88, 7, 70, 15], [95, 92, 3, 65, 9]], dtype=np.float32)
    t = np.arange(2000) / 100
    z_in = (0.02 * np.sin(2 * np.pi * 1.2 * t) + 0.005 * np.sin(2 * np.pi * 0.25 * t)).astype(np.float32)
    spo2 = np.full((2, 60), np.nan, dtype=np.float32)
    hr = np.full((2, 60), np.nan, dtype=np.float32)
    spo2[0], hr[0] = np.linspace(97, 90, 60), 60 + 10 * np.sin(np.arange(60) / 5)
    spo2[1, ::3], hr[1, 5:40] = 95.0 + np.arange(20) % 3, 70.0  # sparse / partially missing results

    # random weights go to a temp dir that shadows the firmware's generated header
    write_weights(model, tmp_path / "apnea" / "model_weights.hpp", window_samples=6000)
    write_test_vectors(model, x, feats, z_in, spo2, hr, tmp_path / "test_vectors.hpp")
    run = build_and_run_host_check(tmp_path)

    assert run.returncode == 0, run.stdout + run.stderr
    assert "zscore PASS" in run.stdout
    assert run.stdout.count("vitals PASS") == 2
    assert run.stdout.count("logit PASS") == 3
