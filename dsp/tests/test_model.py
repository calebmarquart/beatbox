import torch

from beatbox_dsp.model import TinyCNN


def test_output_shape():
    assert TinyCNN()(torch.randn(4, 1, 3000)).shape == (4,)


def test_features_are_causal():
    torch.manual_seed(0)
    m = TinyCNN().eval()
    x = torch.randn(1, 1, 3000)
    x2 = x.clone()
    x2[..., 2000:] += 3.0
    with torch.no_grad():
        f, f2 = m.features(x), m.features(x2)
    # stage-4 feature j depends on input samples <= 16*j + 15
    n = 2000 // 16
    assert torch.equal(f[..., :n], f2[..., :n])
    assert not torch.equal(f[..., n:], f2[..., n:])


def test_param_count():
    assert sum(p.numel() for p in TinyCNN().parameters()) == 76681
