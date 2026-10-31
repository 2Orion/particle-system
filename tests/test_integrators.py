"""积分器测试：解析真值对比、能量守恒、四种方法一致性。

物理基准（呼应课件 P50“Euler 把圆变成螺旋线”）：
1. 自由落体：x(t) = x0 + v0 t + ½ g t²  有解析解；
2. 简谐振子：能量 E = ½v² + ½kx² 守恒 —— 显式 Euler 应漂移增大，
   Verlet/Velocity-Verlet/Leap-Frog 应长期有界。
"""
import numpy as np
import pytest

from core.forces import accumulate_all
from core.integrators import (INTEGRATORS, compute_vel, euler, leapfrog,
                              verlet, velocity_verlet)
from core.pool import ParticlePool


class GravityField:
    """常加速度场 a = g（与 forces.Gravity 等价的测试夹具）。"""
    def __init__(self, g=(0, -9.8, 0)):
        self.g = np.asarray(g, dtype=float)

    def apply(self, pool):
        pool.acc[: pool.count] += self.g


class SpringField:
    """弹簧 a = −k·x（简谐振子），k=1 时周期 T=2π。"""
    def __init__(self, k=1.0):
        self.k = k

    def apply(self, pool):
        pool.acc[: pool.count] += -self.k * pool.pos[: pool.count]


def make_pool(n=1):
    pool = ParticlePool(n + 10)
    pool.spawn(n)
    return pool


def run(method, pool, field, h, steps):
    for _ in range(steps):
        method(pool, h, lambda p, _h: accumulate_all(p, [field]))


# ------------------------------------------------------------- 自由落体

@pytest.mark.parametrize("name", list(INTEGRATORS))
def test_free_fall_matches_analytic(name):
    """h=0.01、1s 内位置误差应远小于特征尺度（二阶方法更小）。"""
    pool = make_pool()
    pool.pos[0] = (0, 0, 0)
    pool.vel[0] = (2.0, 0.0, 0.0)  # 平抛
    field = GravityField()
    h, steps = 0.01, 100           # t = 1s
    method = INTEGRATORS[name]
    run(method, pool, field, h, steps)
    if name == "verlet":
        compute_vel(pool, h)       # Verlet 位置历史在 aux，本身已正确
    t = h * steps
    x_true = 2.0 * t               # 水平：匀速
    y_true = -0.5 * 9.8 * t * t    # 竖直：½gt²
    pos = pool.pos[0]
    assert abs(pos[0] - x_true) < 5e-3, f"{name}: x 误差 {abs(pos[0]-x_true)}"
    assert abs(pos[1] - y_true) < 5e-2, f"{name}: y 误差 {abs(pos[1]-y_true)}"


# ------------------------------------------------------------- 能量守恒

def oscillator_energy(pool, h=None):
    x = pool.pos[0, 0]
    v = pool.vel[0, 0]
    if np.isnan(v):  # 未初始化
        return np.nan
    return 0.5 * v * v + 0.5 * x * x


def test_euler_energy_grows():
    """显式 Euler 在保守系统上能量单调发散（课件 P50 螺旋线）。"""
    pool = make_pool()
    pool.pos[0] = (1.0, 0, 0)
    pool.vel[0] = (0, 0, 0)
    e0 = 0.5
    run(euler, pool, SpringField(), 0.01, 20_000)  # 200 个周期
    assert oscillator_energy(pool) > e0 * 1.05    # 能量显著增长


@pytest.mark.parametrize("name", ["verlet", "leapfrog", "velocity_verlet"])
def test_symplectic_energy_bounded(name):
    """辛积分器能量振荡有界：200 周期后相对偏差 < 5%（Euler 对照组 >5%）。"""
    pool = make_pool()
    pool.pos[0] = (1.0, 0, 0)
    pool.vel[0] = (0, 0, 0)
    e0 = 0.5
    method = INTEGRATORS[name]
    run(method, pool, SpringField(), 0.01, 20_000)
    if name == "verlet":
        compute_vel(pool, 0.01)  # Verlet 的 vel 滞后，先由位置差分估算
    assert abs(oscillator_energy(pool) - e0) / e0 < 0.05


def test_velocity_verlet_orbit_period():
    """简谐振子周期 T=2π：Velocity Verlet 走一个周期应回到起点附近。"""
    pool = make_pool()
    pool.pos[0] = (1.0, 0, 0)
    pool.vel[0] = (0, 0, 0)
    h = 0.001
    run(velocity_verlet, pool, SpringField(), h, int(2 * np.pi / h))
    assert abs(pool.pos[0, 0] - 1.0) < 1e-3


def test_leapfrog_fresh_particle_init():
    """新粒子（aux=NaN）首步应正确初始化半步速度而非报错/发散。"""
    pool = make_pool()
    pool.pos[0] = (0, 10, 0)
    pool.vel[0] = (0, 0, 0)
    leapfrog(pool, 0.01, lambda p, _h: accumulate_all(p, [GravityField()]))
    assert not np.isnan(pool.pos[0]).any()
    assert pool.pos[0, 1] < 10.0  # 已下落


def test_verlet_velocity_estimate():
    """Verlet 的 v(t) 估算：自由落体 v = g·t。"""
    pool = make_pool()
    pool.vel[0] = (0, 0, 0)
    h, steps = 0.01, 100
    run(verlet, pool, GravityField(), h, steps)
    compute_vel(pool, h)
    assert abs(pool.vel[0, 1] - (-9.8 * h * steps)) < 0.05


def test_leapfrog_fresh_particle_first_step():
    """Leap-Frog 新粒子首步：v_{-h/2}=v_0 初始化，位置走 v_0·h − ¼a·h²（kick 后）。"""
    pool = make_pool()
    pool.pos[0] = (0, 0, 0)
    pool.vel[0] = (1.0, 0.0, 0.0)
    h = 0.01
    leapfrog(pool, h, lambda p, _h: accumulate_all(p, [GravityField()]))
    # v_{h/2} = v_0 + a·h；x(h) = x_0 + v_{h/2}·h = v_0·h + a·h²
    assert abs(pool.pos[0, 0] - h) < 1e-12
    assert abs(pool.pos[0, 1] + 9.8 * h * h) < 1e-9


def test_all_integrators_registered():
    assert set(INTEGRATORS) == {"euler", "verlet", "leapfrog", "velocity_verlet"}
