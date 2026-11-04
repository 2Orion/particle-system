"""文字 → 点云采样测试：掩膜形态、世界坐标归一化、重采样正确性。"""
import numpy as np
import pytest

from utils.sampling import (mask_to_points, render_text_mask, sample_points,
                            text_targets)


def test_render_text_mask_nonempty():
    mask = render_text_mask("A")
    assert mask.dtype == bool
    assert mask.sum() > 100                    # 字母 A 有足够笔画像素


def test_render_empty_text_gives_empty_mask():
    assert render_text_mask("").sum() == 0
    assert render_text_mask("   ").sum() == 0  # 全空白：没有笔画像素


def test_mask_to_points_centered_at_origin():
    """点云应以笔画包围盒中心为原点（画布留白不计入）。"""
    mask = render_text_mask("粒子系统")
    pts = mask_to_points(mask, world_height=3.0)
    assert len(pts) > 0
    # 包围盒中心 ≈ 原点（允许半像素误差）
    mid = (pts[:, :2].min(axis=0) + pts[:, :2].max(axis=0)) / 2
    assert np.allclose(mid, 0.0, atol=0.02)
    assert np.allclose(pts[:, 2], 0.0)         # 默认平面


def test_mask_to_points_height_matches_world_height():
    """y 跨度应等于 world_height（按笔画高度缩放而非画布高度）。"""
    mask = render_text_mask("粒子系统")
    pts = mask_to_points(mask, world_height=3.0)
    span = pts[:, 1].max() - pts[:, 1].min()
    assert span == pytest.approx(3.0, rel=0.02)


def test_mask_to_points_y_is_flipped():
    """图像 y 向下，世界 y 向上：掩膜最上一行应映射到最大 y。"""
    mask = np.zeros((10, 10), dtype=bool)
    mask[0, 5] = True                          # 顶部单点
    mask[9, 5] = True                          # 底部单点
    pts = mask_to_points(mask, world_height=9.0)
    top_y = pts[0, 1]                          # 行优先：先取到第 0 行
    bottom_y = pts[1, 1]
    assert top_y > bottom_y


def test_mask_to_points_empty_mask():
    assert mask_to_points(np.zeros((16, 16), dtype=bool)).shape == (0, 3)


def test_mask_to_points_z_spread():
    mask = render_text_mask("A")
    pts = mask_to_points(mask, world_height=2.0, z_spread=0.5)
    assert pts[:, 2].std() > 0.05              # 有厚度
    assert np.abs(pts[:, 2]).max() <= 0.5


# ---------------------------------------------------------------- 重采样

def test_sample_points_exact_count_downsample():
    pts = np.random.rand(1000, 3)
    out = sample_points(pts, 300)
    assert out.shape == (300, 3)


def test_sample_points_exact_count_upsample():
    pts = np.random.rand(100, 3)
    out = sample_points(pts, 500)
    assert out.shape == (500, 3)


def test_sample_points_downsample_is_deterministic():
    """系统抽样（等间隔）而非随机 → 同样输入得同样输出，便于复现。"""
    pts = np.arange(1000, dtype=float).reshape(-1, 1).repeat(3, axis=1)
    a = sample_points(pts, 100)
    b = sample_points(pts, 100)
    assert np.array_equal(a, b)


def test_sample_points_downsample_covers_range():
    """下采样后仍覆盖原点云的首尾（不是只取前 n 个）。"""
    pts = np.arange(1000, dtype=float).reshape(-1, 1).repeat(3, axis=1)
    out = sample_points(pts, 100)
    assert out[:, 0].min() == pts[:, 0].min()
    assert out[:, 0].max() == pts[:, 0].max()


def test_sample_points_upsample_jitters():
    """上采样复制点要加抖动，否则重叠成一个点看不见笔画。"""
    pts = np.array([[0.0, 0.0, 0.0]])
    out = sample_points(pts, 100)
    assert out.shape == (100, 3)
    assert np.linalg.norm(out, axis=1).std() > 0   # 不是全部重合


def test_sample_points_edge_cases():
    assert sample_points(np.zeros((10, 3)), 0).shape == (0, 3)
    assert sample_points(np.zeros((0, 3)), 5).shape == (5, 3)


def test_text_targets_end_to_end():
    pts = text_targets("TEST", 2000, world_height=2.0)
    assert pts.shape == (2000, 3)
    assert np.isfinite(pts).all()
    assert pts[:, 1].max() - pts[:, 1].min() == pytest.approx(2.0, rel=0.05)


def test_text_targets_different_texts_differ():
    a = text_targets("AB", 500)
    b = text_targets("CD", 500)
    assert not np.allclose(a, b)
