"""碰撞测试：课件 P42 检测条件与 P43 响应公式。"""
import numpy as np
import pytest

from core.collisions import KillBox, PlaneCollider
from core.pool import ParticlePool


def make_pool(positions, velocities):
    pool = ParticlePool(len(positions) + 5)
    _, end = pool.spawn(len(positions))
    pool.pos[:end] = positions
    pool.vel[:end] = velocities
    return pool


def test_no_collision_when_above_plane():
    pool = make_pool([(0, 1, 0)], [(0, -1, 0)])
    ground = PlaneCollider(point=(0, 0, 0), normal=(0, 1, 0))
    assert ground.resolve(pool) == 0


def test_collision_only_when_moving_toward_plane():
    """穿入但正在离开（v·N>0）的粒子不响应，避免二次弹跳。"""
    pool = make_pool([(0, -0.1, 0)], [(0, 2.0, 0)])  # 已在地下但向上飞
    ground = PlaneCollider(point=(0, 0, 0), normal=(0, 1, 0))
    assert ground.resolve(pool) == 0


def test_bounce_reflects_normal_component():
    """v_new = −ε·v_n + v_t（课件 P43）。"""
    pool = make_pool([(0, -0.01, 0)], [(2.0, -3.0, 0)])
    ground = PlaneCollider(point=(0, 0, 0), normal=(0, 1, 0),
                           restitution=0.5, friction=0.0)
    hits = ground.resolve(pool)
    assert hits == 1
    assert np.allclose(pool.vel[0], (2.0, 1.5, 0))
    assert pool.pos[0, 1] == pytest.approx(0.0, abs=1e-12)


def test_friction_reduces_tangential():
    pool = make_pool([(0, -0.01, 0)], [(2.0, -3.0, 0)])
    ground = PlaneCollider(point=(0, 0, 0), normal=(0, 1, 0),
                           restitution=0.5, friction=0.25)
    ground.resolve(pool)
    assert np.allclose(pool.vel[0], (1.5, 1.5, 0))


def test_restitution_zero_kills_vertical_motion():
    pool = make_pool([(0, -0.01, 0)], [(1.0, -5.0, 0)])
    ground = PlaneCollider(point=(0, 0, 0), normal=(0, 1, 0),
                           restitution=0.0, friction=0.0)
    ground.resolve(pool)
    assert np.allclose(pool.vel[0], (1.0, 0.0, 0))


def test_position_projected_back_to_plane():
    pool = make_pool([(1.0, -0.5, 2.0)], [(0, -1, 0)])
    ground = PlaneCollider(point=(0, 0, 0), normal=(0, 1, 0))
    ground.resolve(pool)
    assert pool.pos[0, 1] == pytest.approx(0.0)
    assert pool.pos[0, 0] == pytest.approx(1.0)  # 切向位置不动


def test_collision_invalidates_aux():
    """碰撞显式改速度，aux 应标 NaN 让积分器重置历史。"""
    pool = make_pool([(0, -0.01, 0)], [(0, -1, 0)])
    pool.aux[0] = 5.0
    ground = PlaneCollider(point=(0, 0, 0), normal=(0, 1, 0))
    ground.resolve(pool)
    assert np.isnan(pool.aux[0]).any()


def test_tilted_plane():
    """斜面：法向 (1,1,0)/√2。粒子以 (−1,−1,0)（正对平面）撞入应完全弹性反射。"""
    pool = make_pool([(-0.1, -0.1, 0)], [(-1.0, -1.0, 0)])
    slope = PlaneCollider(point=(0, 0, 0), normal=(1, 1, 0), restitution=1.0)
    slope.resolve(pool)
    v = pool.vel[0]
    # 完全弹性：v_new = v − 2(v·N)N
    n = np.array([1, 1, 0]) / np.sqrt(2)
    v0 = np.array([-1.0, -1.0, 0.0])
    expected = v0 - 2 * (v0 @ n) * n
    assert np.allclose(v, expected, atol=1e-12)


def test_kill_box_flags_outside():
    pool = make_pool([(0, 0, 0), (100, 0, 0), (0, -50, 0)], np.zeros((3, 3)))
    kb = KillBox(lo=(-10, -10, -10), hi=(10, 10, 10))
    outside = kb.outside(pool)
    assert outside.tolist() == [False, True, True]
