"""
Sample-by-sample reference implementation of the front end and model.

This is the specification the device C code copies: every operation here processes one
new sample and keeps only small per-layer state. Tests check it reproduces the batch
(PyTorch / SciPy) results.
"""

import numpy as np
from torch import nn

from beatbox_dsp.model import TinyCNN
from beatbox_dsp.preprocess import CMSIS_COEFFS, ZSCORE_EPS, ZSCORE_N


class StreamingFrontEnd:
    """Biquad cascade (direct form I, CMSIS coefficient order) then sliding z-score."""

    def __init__(self):
        self.stages = CMSIS_COEFFS.reshape(-1, 5)
        self.state = np.zeros((len(self.stages), 4))  # x[n-1], x[n-2], y[n-1], y[n-2] per stage
        self.ring = np.zeros(ZSCORE_N)
        self.count = 0

    def step(self, x: float) -> float:
        for i, (b0, b1, b2, a1, a2) in enumerate(self.stages):
            x1, x2, y1, y2 = self.state[i]
            y = b0 * x + b1 * x1 + b2 * x2 + a1 * y1 + a2 * y2
            self.state[i] = (x, x1, y, y1)
            x = y
        self.ring[self.count % ZSCORE_N] = x
        self.count += 1
        if self.count < ZSCORE_N:
            return float("nan")
        return float((x - self.ring.mean()) / (self.ring.std() + ZSCORE_EPS))


class _Conv:
    """Causal Conv1d: keeps the last k inputs per channel (zeros = the training left pad)."""

    def __init__(self, conv: nn.Conv1d):
        self.w = conv.weight.detach().double().numpy()  # (out, in, k)
        self.b = conv.bias.detach().double().numpy()

    def reset(self):
        self.buf = np.zeros(self.w.shape[1:])  # (in, k), column -1 = newest

    def step(self, x):
        self.buf = np.roll(self.buf, -1, axis=1)
        self.buf[:, -1] = x
        return np.einsum("oik,ik->o", self.w, self.buf) + self.b


class _Elu:
    def reset(self):
        pass

    def step(self, x):
        return np.where(x > 0, x, np.expm1(x))


class _MaxPool2:
    """Emits max of each non-overlapping pair; an unpaired trailing value is never emitted."""

    def reset(self):
        self.held = None

    def step(self, x):
        if self.held is None:
            self.held = x
            return None
        out, self.held = np.maximum(self.held, x), None
        return out


class _Gru:
    """Stacked GRU, PyTorch gate order r, z, n."""

    def __init__(self, gru: nn.GRU):
        def g(name):
            return getattr(gru, name).detach().double().numpy()

        self.layers = [
            (g(f"weight_ih_l{k}"), g(f"weight_hh_l{k}"), g(f"bias_ih_l{k}"), g(f"bias_hh_l{k}"))
            for k in range(gru.num_layers)
        ]
        self.hidden = gru.hidden_size

    def reset(self):
        self.h = [np.zeros(self.hidden) for _ in self.layers]

    def step(self, x):
        for k, (w_ih, w_hh, b_ih, b_hh) in enumerate(self.layers):
            gi = w_ih @ x + b_ih
            gh = w_hh @ self.h[k] + b_hh
            r = 1 / (1 + np.exp(-(gi[: self.hidden] + gh[: self.hidden])))
            z = 1 / (1 + np.exp(-(gi[self.hidden : 2 * self.hidden] + gh[self.hidden : 2 * self.hidden])))
            n = np.tanh(gi[2 * self.hidden :] + r * gh[2 * self.hidden :])
            self.h[k] = (1 - z) * n + z * self.h[k]
            x = self.h[k]
        return x


class StreamingModel:
    def __init__(self, model: TinyCNN):
        self.layers = []
        for m in model.features:
            if isinstance(m, nn.Sequential):  # (ConstantPad1d, Conv1d) causal conv
                self.layers.append(_Conv(m[1]))
            elif isinstance(m, nn.ELU):
                self.layers.append(_Elu())
            elif isinstance(m, nn.MaxPool1d):
                self.layers.append(_MaxPool2())
            else:
                raise TypeError(f"unsupported layer {m}")
        self.gru = _Gru(model.gru)
        lin1, _, lin2 = model.head
        self.head = [(l.weight.detach().double().numpy(), l.bias.detach().double().numpy()) for l in (lin1, lin2)]
        self.reset()

    def reset(self):
        for layer in self.layers:
            layer.reset()
        self.gru.reset()

    def step(self, x: float) -> None:
        v = np.array([x], dtype=np.float64)
        for layer in self.layers:
            v = layer.step(v)
            if v is None:  # a pool is waiting for its pair
                return
        self.gru.step(v)

    def logit(self) -> float:
        (w1, b1), (w2, b2) = self.head
        a = w1 @ self.gru.h[-1] + b1
        a = np.where(a > 0, a, np.expm1(a))
        return float((w2 @ a + b2)[0])


def stream_window(sm: StreamingModel, x: np.ndarray) -> float:
    """Reset, stream one window sample by sample, return the end-of-window logit."""
    sm.reset()
    for v in x:
        sm.step(float(v))
    return sm.logit()
