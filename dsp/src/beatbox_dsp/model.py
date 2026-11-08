"""
Causal CNN + GRU apnea window classifier (architecture after Jiang et al. 2023,
narrowed to fit the STM32; see the design spec).
"""

import torch
from torch import nn

from beatbox_dsp.data import N_FEATS


def causal_conv(c_in: int, c_out: int, k: int = 3) -> nn.Sequential:
    """Conv1d that only sees the current and past samples (left padding only)."""
    return nn.Sequential(nn.ConstantPad1d((k - 1, 0), 0.0), nn.Conv1d(c_in, c_out, kernel_size=k))


class TinyCNN(nn.Module):
    def __init__(self, widths=(8, 16, 32, 64), hidden_size=64, fc_hidden=32, n_feats=N_FEATS):
        super().__init__()

        # Per-window vitals (SpO2/HR) are standardized with training-set stats kept in the
        # model, so the exported weights carry everything the device needs
        self.register_buffer("feat_mean", torch.zeros(n_feats))
        self.register_buffer("feat_std", torch.ones(n_feats))

        layers = []
        channel = 1
        for w in widths:
            layers += [
                causal_conv(channel, w),
                causal_conv(w, w),
                nn.ELU(),
                nn.MaxPool1d(2),
            ]
            channel = w
        self.features = nn.Sequential(*layers)

        self.gru = nn.GRU(input_size=channel, hidden_size=hidden_size, num_layers=2, batch_first=True)

        self.head = nn.Sequential(
            nn.Linear(hidden_size + n_feats, fc_hidden),
            nn.ELU(),
            nn.Linear(fc_hidden, 1),
        )

    def set_feature_norm(self, mean: torch.Tensor, std: torch.Tensor) -> None:
        self.feat_mean.copy_(mean)
        self.feat_std.copy_(std)

    def forward(self, x, feats):
        f = self.features(x).permute(0, 2, 1)  # (B, C, T) -> (B, T, C)
        _, h_n = self.gru(f)
        v = (feats - self.feat_mean) / self.feat_std
        return self.head(torch.cat([h_n[-1], v], dim=1)).squeeze(1)  # (B,) one logit per window
