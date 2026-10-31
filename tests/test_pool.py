"""粒子池测试：spawn/compact 语义、索引连续性、边界情形。"""
import numpy as np
import pytest

from core.pool import ParticlePool


def test_spawn_returns_contiguous_range():
    pool = ParticlePool(100)
    start, end = pool.spawn(10)
    assert (start, end) == (0, 10)
    assert pool.count == 10
    start2, end2 = pool.spawn(5)
    assert (start2, end2) == (10, 15)
    assert pool.count == 15


def test_spawn_truncates_at_capacity():
    pool = ParticleFlow = ParticlePool(10)
    pool.spawn(8)
    start, end = pool.spawn(5)  # 只剩 2 个位置
    assert end - start == 2
    assert pool.count == 10
    # 满池后再申请返回空区间
    s, e = pool.spawn(3)
    assert s == e == 10


def test_spawn_marks_aux_nan():
    pool = ParticlePool(10)
    pool.aux[:] = 0.0
    pool.spawn(3)
    assert np.isnan(pool.aux[:3]).all()
    assert np.isnan(pool.aux[3:]).sum() == 0  # 未分配区域不受影响


def test_compact_removes_dead_and_keeps_order():
    pool = ParticlePool(10)
    _, end = pool.spawn(5)
    pool.pos[:5] = np.arange(15).reshape(5, 3)
    pool.life[:5] = np.array([1.0, 0.0, 1.0, 0.0, 1.0])
    dead = pool.compact(pool.life[: pool.count] > 0)
    assert dead == 2
    assert pool.count == 3
    assert np.array_equal(pool.pos[0], [0, 1, 2])
    assert np.array_equal(pool.pos[1], [6, 7, 8])
    assert np.array_equal(pool.pos[2], [12, 13, 14])


def test_compact_all_dead():
    pool = ParticlePool(10)
    pool.spawn(5)
    dead = pool.compact(np.zeros(5, dtype=bool))
    assert dead == 5
    assert pool.count == 0
    # 空池之后还能继续 spawn
    start, end = pool.spawn(3)
    assert (start, end) == (0, 3)


def test_compact_rejects_wrong_shape():
    pool = ParticlePool(10)
    pool.spawn(5)
    with pytest.raises(ValueError):
        pool.compact(np.zeros(4, dtype=bool))


def test_life_fraction():
    pool = ParticlePool(10)
    pool.spawn(2)
    pool.life[:2] = [0.25, 0.0]
    pool.max_life[:2] = [1.0, 2.0]
    frac = pool.life_fraction
    assert frac[0] == pytest.approx(0.25)
    assert frac[1] == pytest.approx(0.0)


def test_capacity_validation():
    with pytest.raises(ValueError):
        ParticlePool(0)
