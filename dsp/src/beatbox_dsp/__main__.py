"""
Runner for the model training workflow
"""

import numpy as np
import torch

from torch.utils.data import DataLoader, TensorDataset, random_split
from torch import nn

class TinyCNN(nn.Module):
    def __init__(self):
        super().__init__()

        weights = [32, 64, 128, 256]
        layers = []
        channel = 1
        for w in weights:
            layers += [
                nn.Conv1d(channel, w, kernel_size=3, padding=1),
                nn.Conv1d(w, w, kernel_size=3, padding=1),
                nn.ELU(),
                nn.MaxPool1d(2),
            ]
            channel = w

        self.features = nn.Sequential(*layers)

        hidden_size = 64
        fc_hidden = 32
        self.gru = nn.GRU(input_size=channel, hidden_size=hidden_size, num_layers=2, batch_first=True)
        self.head = nn.Sequential(
            nn.Linear(hidden_size, fc_hidden),
            nn.ELU(),
            nn.Linear(fc_hidden, 1)
        )

    def forward(self, x):
        f = self.features(x)
        f = f.permute(0, 2, 1)
        _, h_n = self.gru(f)

        if isinstance(h_n, tuple):
            h_n = h_n[0]

        return self.head(h_n[-1]).squeeze(1)

if __name__ == "__main__":
    a = torch.tensor([1.0, 2.0, 3.0])
    b = torch.from_numpy(np.ones(3, dtype=np.float32))

    w = torch.tensor(2.0, requires_grad=True)
    loss = (w * 3.0 - 9.0) ** 2
    loss.backward()

    ## Make fake data

    fs, n = 80, 2000
    t = torch.arange(fs) / fs
    labels = torch.randint(0, 2, (n,)).float()
    amp = 1.0 - 0.6 * labels[:, None] * t
    x = amp * torch.sin(2 * torch.pi * 1.2 * t) + 0.2 * torch.randn(n, fs)
    x = x[:, None, :]
    print(x.shape, labels.mean())    

    ds = TensorDataset(x, labels)
    train_ds, val_ds = random_split(ds, [1600, 400], generator=torch.Generator().manual_seed(0)) # TODO: FIX
    train_dl = DataLoader(train_ds, batch_size=64, shuffle=True)
    val_dl = DataLoader(val_ds, batch_size=256)

    model = TinyCNN()
    print(model)
    print("params:", sum(p.numel() for p in model.parameters()))

    loss_fn = nn.BCEWithLogitsLoss()
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)

    for epoch in range(10):
        model.train()
        for xb, yb in train_dl:
            opt.zero_grad()
            loss = loss_fn(model(xb), yb)
            loss.backward()
            opt.step()
    
        model.eval()
        with torch.no_grad():
            correct = sum(((model(xb) > 0).float() == yb).sum().item() for xb, yb in val_dl)

        print(f"epoch {epoch}: loss {loss.item():.3f}  val acc {correct / len(val_ds):.3f}")

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
