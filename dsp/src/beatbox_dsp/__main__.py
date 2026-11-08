"""
Runner for the model training workflow
"""

import argparse
import time

import numpy as np
import torch
from scipy.stats import rankdata
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from beatbox_dsp import data
from beatbox_dsp.model import TinyCNN

MODEL_PATH = data.DEFAULT_NPZ.parent / "model.pt"
QUICK_TRAIN_WINDOWS = 8_000


def metrics(logits: np.ndarray, y_soft: np.ndarray) -> dict[str, float]:
    """Per-window metrics. Truth: soft label >= LABEL_THRESHOLD; prediction: p >= 0.5 (logit > 0)."""
    pred = logits > 0
    pos = y_soft >= data.LABEL_THRESHOLD
    tp, fn = (pred & pos).sum(), (~pred & pos).sum()
    tn, fp = (~pred & ~pos).sum(), (pred & ~pos).sum()
    sens = tp / max(tp + fn, 1)
    spec = tn / max(tn + fp, 1)
    prec = tp / max(tp + fp, 1)
    f1 = 2 * prec * sens / max(prec + sens, 1e-12)
    # AUROC = probability a random positive scores above a random negative
    ranks = rankdata(logits)
    n_pos, n_neg = pos.sum(), (~pos).sum()
    auroc = (ranks[pos].sum() - n_pos * (n_pos + 1) / 2) / max(n_pos * n_neg, 1)
    return {"sens": sens, "spec": spec, "prec": prec, "f1": f1, "auroc": auroc}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=10)
    ap.add_argument("--quick", action="store_true",
                    help=f"train on {QUICK_TRAIN_WINDOWS:,} random windows for a fast sanity check")
    args = ap.parse_args()

    torch.manual_seed(0)
    d = data.load()
    train_p, val_p = data.split_patients(d)
    train = data.make_windows(d, train_p, hop_s=data.WINDOW_S // 2)  # 50% overlap
    val = data.make_windows(d, val_p, hop_s=data.WINDOW_S)  # back-to-back, as on the device
    del d
    if args.quick:
        keep = np.random.default_rng(0).choice(len(train), QUICK_TRAIN_WINDOWS, replace=False)
        train = data.Windows(x=train.x[keep], y=train.y[keep], patient=train.patient[keep], feats=train.feats[keep])
    print(f"train patients {train_p}\nval patients   {val_p}")
    for name, w in (("train", train), ("val", val)):
        print(f"{name} {len(w):,} windows, positive share (label >= {data.LABEL_THRESHOLD}) "
              f"{(w.y >= data.LABEL_THRESHOLD).mean():.1%}, shape {w.x.shape[1:]}")

    def loader(w: data.Windows, **kw) -> DataLoader:
        return DataLoader(TensorDataset(torch.from_numpy(w.x), torch.from_numpy(w.feats), torch.from_numpy(w.y)), **kw)

    train_dl = loader(train, batch_size=64, shuffle=True)
    val_dl = loader(val, batch_size=256)

    model = TinyCNN()
    feats = torch.from_numpy(train.feats)
    model.set_feature_norm(feats.mean(0), feats.std(0) + 1e-6)
    print("params:", sum(p.numel() for p in model.parameters()))

    loss_fn = nn.BCEWithLogitsLoss()
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)

    best_auroc = -1.0
    for epoch in range(args.epochs):
        t0 = time.time()
        model.train()
        total = 0.0
        for xb, fb, yb in train_dl:
            opt.zero_grad()
            loss = loss_fn(model(xb, fb), yb)
            loss.backward()
            opt.step()
            total += loss.item() * len(yb)

        model.eval()
        with torch.no_grad():
            logits = torch.cat([model(xb, fb) for xb, fb, _ in val_dl]).numpy()
        m = metrics(logits, val.y)

        print(f"epoch {epoch}: train loss {total / len(train):.3f}  "
              + "  ".join(f"{k} {v:.3f}" for k, v in m.items())
              + f"  ({time.time() - t0:.0f} s)", flush=True)

        if m["auroc"] > best_auroc:
            best_auroc = m["auroc"]
            torch.save(model.state_dict(), MODEL_PATH)

    print(f"best val AUROC {best_auroc:.3f}, saved to {MODEL_PATH}")
    print("note: metrics are on validation patients also used for model selection -> slightly optimistic")
    model.load_state_dict(torch.load(MODEL_PATH))

    lines = ["#pragma once", ""]
    for name, tensor in model.state_dict().items():
        cname = name.replace(".", "_")
        vals = tensor.detach().flatten().tolist()
        lines.append(f"// {name} shape {tuple(tensor.shape)}")
        lines.append(f"static const float {cname}[{len(vals)}] = {{")
        lines.append("  " + ", ".join(f"{v:.9g}f" for v in vals))
        lines.append("};\n")
    header = "\n".join(lines)
    print(header[:600])
