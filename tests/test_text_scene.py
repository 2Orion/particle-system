"""文字粒子场景测试：软约束汇聚、morph 重排、鼠标排斥。"""
import numpy as np
import pytest

from core.forces import Attractor, TargetConstraint
from scenes.text_particles import TextParticlesScene


def _settle(scene, seconds=4.0, fps=60):
    for _ in range(int(seconds * fps)):
        scene.update(1 / fps)


def test_scene_builds_with_particles():
    from scenes.base import VALID_TEXTURE
    scene = TextParticlesScene()
    assert scene.count == scene.particle_count
    assert scene.blend == "additive"
    assert scene.texture in VALID_TEXTURE


def test_particles_converge_to_targets():
    """软约束（课件 P25）应把粒子拉到位：收敛后到目标点距离极小。"""
    scene = TextParticlesScene()
    pool = scene.system.pool
    d0 = np.linalg.norm(
        pool.pos[:scene.count] - scene._constraint.targets[:scene.count],
        axis=1).mean()
    _settle(scene, 4.0)
    d1 = np.linalg.norm(
        pool.pos[:scene.count] - scene._constraint.targets[:scene.count],
        axis=1).mean()
    # 初始是绕文字中心的球状散布（半径约 2.5 个世界单位）
    assert d0 > 2.0
    assert d1 < 0.05                            # 汇聚完成
    assert d1 < d0 * 0.02


def test_converged_points_spell_text_shape():
    """汇聚后点云应覆盖文字包围盒（不是塌缩成一点）。"""
    scene = TextParticlesScene()
    _settle(scene, 4.0)
    pos = scene.system.pool.pos[:scene.count]
    # 中文四字：横向跨度远大于纵向
    assert np.ptp(pos[:, 0]) > 6.0
    assert np.ptp(pos[:, 1]) > 2.0


def test_long_text_fits_width_budget():
    """长句子按世界宽度上限整体缩小，否则会横向冲出视野。

    注意是**整体等比缩小**：缩放取 min(高度尺度, 宽度尺度)，
    所以宽度装得下时高度仍保持 world_height。
    """
    scene = TextParticlesScene()
    scene.set_text("Computer Animation")
    targets = scene._constraint.targets[:scene.count]
    width = np.ptp(targets[:, 0])
    height = np.ptp(targets[:, 1])
    assert width <= scene.world_width + 1e-6
    assert width > scene.world_width * 0.9        # 确实用满了宽度预算
    assert height < scene.world_height            # 整体被缩放过（不是拉扁）


def test_set_text_morphs_to_new_targets():
    """换字后目标点改变，粒子重新流动到新目标。"""
    scene = TextParticlesScene(text="粒子")
    _settle(scene, 3.0)
    old_targets = scene._constraint.targets[:scene.count].copy()
    scene.set_text("系统")
    new_targets = scene._constraint.targets[:scene.count]
    assert not np.allclose(old_targets, new_targets)
    _settle(scene, 4.0)
    pool = scene.system.pool
    d = np.linalg.norm(pool.pos[:scene.count] - new_targets, axis=1)
    assert d.mean() < 0.1                       # 已汇聚到新文字


def test_set_text_keeps_particle_count():
    scene = TextParticlesScene(text="粒子")
    _settle(scene, 1.0)
    before = scene.count
    scene.set_text("粒子系统")
    assert scene.count == before


def test_set_text_empty_is_ignored():
    scene = TextParticlesScene()
    text_before = scene.text
    scene.set_text("")
    assert scene.text == text_before


def test_targets_cover_capacity():
    """targets 数组必须覆盖整池容量（池可能多于目标点数）。"""
    scene = TextParticlesScene()
    assert scene._constraint.targets.shape == (scene.capacity, 3)
    assert np.isfinite(scene._constraint.targets).all()


def test_text_is_lifted_off_ground():
    """文字整体抬到 center_y 附近：下半截不能压在 y=0 的网格上。"""
    scene = TextParticlesScene()
    n = scene.count
    targets = scene._constraint.targets[:n]
    low, high = targets[:, 1].min(), targets[:, 1].max()
    assert low > 0.4                       # 最下一笔离地
    assert abs((low + high) / 2 - scene.center_y) < 1e-6
    # morph 之后仍保持同一高度
    scene.set_text("系统")
    targets = scene._constraint.targets[:n]
    assert abs((targets[:, 1].min() + targets[:, 1].max()) / 2 - scene.center_y) < 1e-6


def test_mouse_repeller_added_then_removed():
    scene = TextParticlesScene()
    _settle(scene, 2.0)
    n_before = len(scene.system.forces)
    scene.set_mouse_world((0.0, 0.0, 0.0))
    assert len(scene.system.forces) == n_before + 1
    repeller = scene.system.forces[-1]
    assert isinstance(repeller, Attractor)
    assert repeller.strength < 0                # 负强度 = 排斥

    scene.set_mouse_world((2.0, 1.0, 0.0))
    assert len(scene.system.forces) == n_before + 1   # 不重复添加
    assert np.allclose(scene.system.forces[-1].center, (2.0, 1.0, 0.0))

    scene.set_mouse_world(None)
    assert len(scene.system.forces) == n_before


def test_mouse_repeller_pushes_particles_away():
    """鼠标排斥确实把附近的粒子推开（聚类半径变大）。"""
    scene = TextParticlesScene(text="粒子")
    _settle(scene, 4.0)
    pool = scene.system.pool
    center = np.array([0.0, scene.center_y, 0.0])   # 文字中心（不是原点）
    d_before = np.linalg.norm(pool.pos[:scene.count] - center, axis=1)

    scene.set_mouse_world(center)
    for _ in range(60):
        scene.update(1 / 60)
    d_after = np.linalg.norm(pool.pos[:scene.count] - center, axis=1)
    assert d_after.mean() > d_before.mean()


def test_constraint_uses_energy_form():
    """软约束参数与课件一致：f = −k(x−x_t) − c·v（负梯度 + 阻尼）。"""
    scene = TextParticlesScene()
    tc = scene._constraint
    assert isinstance(tc, TargetConstraint)
    assert tc.k > 0 and tc.damping > 0


def test_shade_brightens_settled_particles():
    """着色回调：越靠拢目标越亮（汇聚进度可视化）。"""
    scene = TextParticlesScene()
    _settle(scene, 4.0)
    pool = scene.system.pool
    d = np.linalg.norm(pool.pos[:scene.count] - scene._constraint.targets[:scene.count],
                       axis=1)
    alpha = pool.color[:scene.count, 3]
    settled = d < 0.1
    loose = d > 1.0
    if settled.any() and loose.any():
        assert alpha[settled].mean() > alpha[loose].mean()


def test_no_particles_escape_killbox():
    scene = TextParticlesScene()
    scene.set_mouse_world((0.0, 0.0, 0.0))
    _settle(scene, 3.0)
    pool = scene.system.pool
    pos = pool.pos[:pool.count]
    assert np.isfinite(pos).all()
    assert np.abs(pos).max() < 30.0


def test_reset_rebuilds_and_rebursts():
    scene = TextParticlesScene()
    _settle(scene, 2.0)
    scene.reset()
    assert scene.count == scene.particle_count
    # 重置后回到爆散状态（离目标很远）
    pool = scene.system.pool
    d = np.linalg.norm(pool.pos[:scene.count] - scene._constraint.targets[:scene.count],
                       axis=1)
    assert d.mean() > 1.0
