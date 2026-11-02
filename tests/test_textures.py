"""纹理测试：程序化纹理的数值性质。"""
import numpy as np
import pytest

from render.textures import gaussian_spot, ring, soft_disc


def test_gaussian_center_bright_edge_dark():
    tex = gaussian_spot(size=65)  # 奇数尺寸：中心像素恰在 (0,0)
    assert tex[..., 3].max() == pytest.approx(1.0, abs=1e-6)
    assert tex[..., 3].min() < 0.01
    # 最亮处在中心
    idx = np.unravel_index(np.argmax(tex[..., 3]), tex[..., 3].shape)
    assert abs(idx[0] - 32) <= 1 and abs(idx[1] - 32) <= 1


def test_gaussian_radially_symmetric():
    tex = gaussian_spot(size=64)
    a = tex[..., 3]
    assert np.allclose(a, a.T, atol=1e-6)          # 对角对称
    assert np.allclose(a, a[::-1, ::-1], atol=1e-6)


def test_soft_disc_opaque_core_transparent_edge():
    tex = soft_disc(size=64)
    a = tex[..., 3]
    assert a[32, 32] == pytest.approx(1.0)         # 中心不透明
    assert a[0, 0] == pytest.approx(0.0)           # 角落透明
    assert a.min() >= 0.0 and a.max() <= 1.0


def test_soft_disc_smoothstep_monotonic_along_radius():
    """沿半径 alpha 单调不增（无振铃）。"""
    tex = soft_disc(size=64)
    a = tex[..., 3]
    center = 31.5
    samples = [a[int(center + r * 31.5), 32] for r in np.linspace(0, 0.99, 40)]
    diffs = np.diff(samples)
    assert (diffs <= 1e-6).all()


def test_ring_peak_between_center_and_edge():
    """环半径 0.7：峰应在 r≈0.7 处（列 ~9 或 ~53），中心与边缘低。"""
    tex = ring(size=64)
    a = tex[..., 3]
    row = a[32, :]
    peak = int(np.argmax(row))
    assert peak < 16 or peak > 48                   # 在两侧环带上（r≈0.7）
    assert row[32] < 0.05                           # 中心接近全透明
    assert row[peak] > 0.9                          # 环峰值亮
    # 对称性：左右环带亮度接近
    assert abs(row[9] - row[53]) < 0.1


def test_all_textures_rgba_float():
    for tex in (gaussian_spot(), soft_disc(), ring()):
        assert tex.shape == (64, 64, 4)
        assert tex.dtype == np.float32
        assert tex[..., :3].min() >= 0.0
