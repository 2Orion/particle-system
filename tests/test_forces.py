"""力场测试：方向、大小、公式与课件一致。"""
import numpy as np
import pytest

from core.forces import (Attractor, Drag, Gravity, TargetConstraint,
                         Wind, accumulate_all)
from core.pool import ParticlePool


def make_pool(positions, velocities=None):
    pool = ParticlePool(len(positions) + 5)
    start, end = pool.spawn(len(positions))
    pool.pos[:end] = positions
    if velocities is not None:
        pool.vel[:end] = velocities
    return pool


def test_gravity_uniform():
    pool = make_pool([(0, 0, 0), (1, 2, 3)])
    accumulate_all(pool, [Gravity(g=(0, -9.8, 0))])
    assert np.allclose(pool.acc[:2], (0, -9.8, 0))


def test_drag_linear_opposes_velocity():
    pool = make_pool([(0, 0, 0)], [(3.0, 0, 0)])
    accumulate_all(pool, [Drag(k1=0.5, k2=0.0)])
    assert np.allclose(pool.acc[0], (-1.5, 0, 0))  # a = −k1·v


def test_drag_quadratic():
    pool = make_pool([(0, 0, 0)], [(2.0, 0, 0)])
    accumulate_all(pool, [Drag(k1=0.0, k2=0.25)])
    # a = −k2·|v|·v = −0.25·2·(2,0,0) = (−1,0,0)
    assert np.allclose(pool.acc[0], (-1.0, 0, 0))


def test_drag_reaches_terminal_velocity():
    """重力 + 平方阻力 → 终端速度 v_t = sqrt(g/k2)，积分逼近验证。"""
    from core.integrators import velocity_verlet
    pool = make_pool([(0, 0, 0)], [(0, 0, 0)])
    forces = [Gravity(g=(0, -9.8, 0)), Drag(k2=0.1)]
    v_terminal = np.sqrt(9.8 / 0.1)
    for _ in range(4000):
        velocity_verlet(pool, 0.005, lambda p, h: accumulate_all(p, forces))
    assert abs(pool.vel[0, 1] + v_terminal) < 0.05 * v_terminal


def test_attractor_pulls_toward_center():
    pool = make_pool([(1.0, 0, 0)])
    accumulate_all(pool, [Attractor(center=(0, 0, 0), strength=10.0)])
    assert pool.acc[0, 0] < 0  # 指向中心


def test_repulsor_pushes_away():
    pool = make_pool([(1.0, 0, 0)])
    accumulate_all(pool, [Attractor(center=(0, 0, 0), strength=-10.0)])
    assert pool.acc[0, 0] > 0


def test_attractor_softening_avoids_singularity():
    pool = make_pool([(0.0, 0, 0)])  # 正好在中心
    accumulate_all(pool, [Attractor(center=(0, 0, 0), strength=10.0, softening=0.5)])
    assert np.isfinite(pool.acc[0]).all()


def test_target_constraint_formula():
    """f = −k(x−xt) − c·v（课件 P25 软约束 + 阻尼）。"""
    targets = np.zeros((10, 3))
    targets[0] = (0.5, 0, 0)
    pool = make_pool([(1.0, 0, 0)], [(1.0, 0, 0)])
    tc = TargetConstraint(targets=targets, k=8.0, damping=2.0)
    accumulate_all(pool, [tc])
    # a = −8·(1−0.5) − 2·1 = −6
    assert np.allclose(pool.acc[0], (-6.0, 0, 0))


def test_wind_zero_amplitude_is_constant():
    pool = make_pool([(0, 0, 0), (5, 5, 5)])
    w = Wind(base=(1, 0, 0), amplitude=0.0)
    accumulate_all(pool, [w])
    assert np.allclose(pool.acc[:2], (1, 0, 0))


def test_wind_turbulence_varies_in_space():
    """同一定常风下，不同位置湍流分量应不同（空间相关性）。"""
    pool = make_pool([(0, 0, 0), (10.0, 0, 0)])
    w = Wind(base=(1, 0, 0), amplitude=1.0)
    accumulate_all(pool, [w])
    assert not np.allclose(pool.acc[0], pool.acc[1])


def test_wind_perp_basis_cached_and_stable():
    """垂直基只算一次：多次 apply 结果完全一致（缓存不引入漂移）。"""
    pool = make_pool([(0.0, 0.0, 0.0), (3.0, 1.0, -2.0)])
    w = Wind(base=(1.0, 0.0, 0.5), amplitude=1.2, frequency=0.0, spatial=0.7)
    accumulate_all(pool, [w])
    first = pool.acc[:2].copy()
    assert w._basis is not None                # 已缓存
    for _ in range(20):
        accumulate_all(pool, [w])
    assert np.allclose(pool.acc[:2], first)


def test_wind_perp_basis_orthogonal_to_base():
    """两个湍流方向都与定常风垂直，不会与之同轴抵消。"""
    for base in ((1, 0, 0), (0, 0, 1), (1, 1, 1), (0, 1, 0)):
        w = Wind(base=base, amplitude=1.0)
        d1, d2 = w._perp_basis()
        b = np.asarray(base, dtype=float)
        b = b / np.linalg.norm(b)
        assert abs(float(np.dot(d1, b))) < 1e-9
        assert abs(float(np.dot(d2, b))) < 1e-9
        assert abs(float(np.dot(d1, d2))) < 1e-9
        assert np.linalg.norm(d1) == pytest.approx(1.0)
        assert np.linalg.norm(d2) == pytest.approx(1.0)


def test_wind_base_along_z_does_not_degenerate():
    """base 沿 z 时 (−b1, b0, 0) 退化为零向量 → 必须换方向，不能除零出 NaN。"""
    pool = make_pool([(0.0, 0.0, 0.0)])
    w = Wind(base=(0.0, 0.0, 1.0), amplitude=1.0)
    accumulate_all(pool, [w])
    assert np.isfinite(pool.acc[0]).all()
    assert np.linalg.norm(pool.acc[0]) > 0


def test_wind_empty_pool_safe():
    pool = ParticlePool(8)
    accumulate_all(pool, [Wind(base=(1, 0, 0), amplitude=1.0)])


def test_accumulate_clears_previous():
    pool = make_pool([(0, 0, 0)])
    pool.acc[0] = (99, 99, 99)
    accumulate_all(pool, [])
    assert np.allclose(pool.acc[0], 0)
