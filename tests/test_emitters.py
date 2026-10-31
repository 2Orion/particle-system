"""发射器测试：数量公式（课件 P13）、属性分布（课件 P14）、填充完整性。"""
import numpy as np
import pytest

from core.emitters import (Emitter, PointEmitter, SphereBurstEmitter,
                           VolumeEmitter, emission_count, tangent_basis)
from core.pool import ParticlePool


def test_emission_count_formula():
    """n = (m + v·rand())·A 应落在 [(m−v)A, (m+v)A]。"""
    np.random.seed(0)
    m, v = 100, 20
    for _ in range(200):
        n = emission_count(m, v, 1.0)
        assert 80 <= n <= 120


def test_emission_count_area_factor():
    np.random.seed(1)
    counts = [emission_count(100, 0, 2.0) for _ in range(10)]
    assert all(c == 200 for c in counts)  # v=0 时严格 = m·A


def test_point_emitter_speed_within_bounds():
    np.random.seed(2)
    pool = ParticlePool(1000)
    em = PointEmitter(origin=(0, 0, 0), direction=(0, 1, 0),
                      speed_mean=10, speed_var=2, angle_var=0.2,
                      rate_mean=500, rate_var=0)
    emitted = em.emit(pool, dt=1.0)
    assert emitted == 500
    speeds = np.linalg.norm(pool.vel[:500], axis=1)
    assert speeds.min() >= 8.0 and speeds.max() <= 12.0


def test_point_emitter_cone_direction():
    """方向锥：与主轴夹角不超过 angle_var + 数值余量。"""
    np.random.seed(3)
    pool = ParticlePool(2000)
    em = PointEmitter(origin=(0, 0, 0), direction=(0, 1, 0),
                      angle_var=0.1, speed_var=0, rate_mean=1000, rate_var=0)
    em.emit(pool, dt=1.0)
    dirs = pool.vel[:1000] / np.linalg.norm(pool.vel[:1000], axis=1, keepdims=True)
    angles = np.arccos(np.clip(dirs @ np.array([0, 1, 0]), -1, 1))
    assert angles.max() < 0.1 + 1e-6


def test_point_emitter_life_fraction_bounds():
    np.random.seed(4)
    pool = ParticlePool(1000)
    em = PointEmitter(life_mean=2.0, life_var=0.5, rate_mean=100, rate_var=0)
    em.emit(pool, dt=1.0)
    assert pool.life[:100].min() >= 1.5
    assert pool.life[:100].max() <= 2.5
    assert np.allclose(pool.max_life[:100], pool.life[:100])


def test_volume_emitter_within_box():
    np.random.seed(5)
    pool = ParticlePool(2000)
    em = VolumeEmitter(center=(0, 5, 0), half_extents=(10, 1, 10),
                       rate_mean=1000, rate_var=0)
    em.emit(pool, dt=1.0)
    pos = pool.pos[:1000]
    assert pos[:, 0].min() >= -10 and pos[:, 0].max() <= 10
    assert pos[:, 1].min() >= 4 and pos[:, 1].max() <= 6
    assert pos[:, 2].min() >= -10 and pos[:, 2].max() <= 10


def test_sphere_burst_uniform_directions():
    """球面均匀：方向点集的均值应接近 0（各向同性），范数恒为 speed 范围。"""
    np.random.seed(6)
    pool = ParticlePool(5000)
    em = SphereBurstEmitter(center=(0, 10, 0), speed_mean=8, speed_var=0)
    n = em.burst(pool, 4000)
    assert n == 4000
    dirs = pool.vel[:n] / np.linalg.norm(pool.vel[:n], axis=1, keepdims=True)
    assert np.abs(dirs.mean(axis=0)).max() < 0.05          # 各向同性
    assert np.allclose(pool.pos[:n], (0, 10, 0))           # 同一起点


def test_emit_truncates_when_pool_full():
    pool = ParticlePool(50)
    em = PointEmitter(rate_mean=100, rate_var=0)
    n = em.emit(pool, dt=1.0)
    assert n == 50
    assert pool.count == 50
    n2 = em.emit(pool, dt=1.0)
    assert n2 == 0


def test_tangent_basis_orthonormal():
    for d in [(0, 1, 0), (1, 0, 0), (0.3, -0.5, 0.8)]:
        d = np.asarray(d, dtype=float)
        d /= np.linalg.norm(d)
        t1, t2 = tangent_basis(d)
        assert abs(np.dot(t1, d)) < 1e-12
        assert abs(np.dot(t2, d)) < 1e-12
        assert abs(np.dot(t1, t2)) < 1e-12
        assert np.allclose(np.cross(t1, t2), d, atol=1e-12) or \
            np.allclose(np.cross(t1, t2), -d, atol=1e-12)
