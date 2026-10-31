"""发射器：决定新粒子的数量（课件 P13）与初始属性（课件 P14）。

数量：  n = (m + v·rand())·A   rand∈[−1,1]
属性：  Value = mean + Rand()·variance

发射器只负责把新粒子填入池（调用 pool.spawn），不持有粒子状态。
"""
from __future__ import annotations

import numpy as np

from .pool import ParticlePool


def emission_count(mean: float, variance: float, area_factor: float = 1.0) -> int:
    """课件 P13 方法二：n = (m + v·rand())·A，返回非负整数。"""
    n = (mean + variance * np.random.uniform(-1.0, 1.0)) * area_factor
    return max(0, int(n))


def tangent_basis(direction: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """返回与 direction 垂交的两个正交单位向量 t1, t2（构成局部平面基）。"""
    helper = np.array([1.0, 0.0, 0.0])
    if abs(float(np.dot(helper, direction))) > 0.9:
        helper = np.array([0.0, 1.0, 0.0])
    t1 = np.cross(direction, helper)
    t1 /= np.linalg.norm(t1)
    t2 = np.cross(direction, t1)
    return t1, t2


class Emitter:
    """发射器基类：子类实现 _fill() 填充新粒子属性。"""

    def __init__(self, rate_mean: float = 100.0, rate_var: float = 20.0,
                 area_adaptive: bool = False) -> None:
        self.rate_mean = rate_mean        # 每秒平均粒子数 m
        self.rate_var = rate_var          # 数量变化幅度 v
        self.area_adaptive = area_adaptive  # 是否乘屏幕面积因子 A（渲染层提供）

    def emission_count(self, dt: float, area_factor: float = 1.0) -> int:
        """本帧发射数量：每秒率 × 步长，可选面积自适应。"""
        a = area_factor if self.area_adaptive else 1.0
        return emission_count(self.rate_mean * dt, self.rate_var * dt, a)

    def emit(self, pool: ParticlePool, dt: float, area_factor: float = 1.0) -> int:
        """生成新粒子并初始化属性，返回实际生成数。"""
        n_requested = self.emission_count(dt, area_factor)
        start, end = pool.spawn(n_requested)
        if end > start:
            self._fill(pool, start, end)
        return end - start

    def _fill(self, pool: ParticlePool, start: int, end: int) -> None:
        raise NotImplementedError


class PointEmitter(Emitter):
    """点源：位置附近抖动，速度在方向锥内分布（烟花上升体、喷泉口）。

    速度大小、锥角、寿命、尺寸均按 mean + variance·rand 初始化（课件 P14）。
    """

    def __init__(self, origin=(0.0, 0.0, 0.0), direction=(0.0, 1.0, 0.0),
                 speed_mean=10.0, speed_var=2.0,
                 angle_var=0.15, pos_jitter=0.05,
                 life_mean=1.5, life_var=0.3,
                 size_mean=0.08, size_var=0.02,
                 color=(1.0, 0.8, 0.4, 1.0),
                 **kwargs) -> None:
        super().__init__(**kwargs)
        self.origin = np.asarray(origin, dtype=float)
        d = np.asarray(direction, dtype=float)
        self.direction = d / np.linalg.norm(d)
        self.speed_mean, self.speed_var = speed_mean, speed_var
        self.angle_var = angle_var          # 锥半角扰动幅度（弧度）
        self.pos_jitter = pos_jitter
        self.life_mean, self.life_var = life_mean, life_var
        self.size_mean, self.size_var = size_mean, size_var
        self.color = np.asarray(color, dtype=float)

    def _fill(self, pool: ParticlePool, start: int, end: int) -> None:
        m = end - start
        # 位置：origin + 均匀抖动
        pool.pos[start:end] = self.origin + np.random.uniform(
            -self.pos_jitter, self.pos_jitter, size=(m, 3))
        pool.prev_pos[start:end] = pool.pos[start:end]
        # 速度：大小 mean+var·rand；方向 = 锥内扰动（极角~angle_var，方位角全周）
        speed = self.speed_mean + self.speed_var * np.random.uniform(-1, 1, m)
        polar = np.abs(np.random.uniform(-self.angle_var, self.angle_var, m))
        azim = np.random.uniform(0.0, 2.0 * np.pi, m)
        t1, t2 = tangent_basis(self.direction)
        sin_p, cos_p = np.sin(polar), np.cos(polar)
        v = (speed * cos_p)[:, None] * self.direction[None] \
            + (speed * sin_p)[:, None] * (np.cos(azim)[:, None] * t1[None]
                                          + np.sin(azim)[:, None] * t2[None])
        pool.vel[start:end] = v
        pool.acc[start:end] = 0.0
        pool.mass[start:end] = 1.0
        pool.life[start:end] = self.life_mean + \
            self.life_var * np.random.uniform(-1, 1, m)
        pool.max_life[start:end] = pool.life[start:end]
        pool.size[start:end] = self.size_mean + \
            self.size_var * np.random.uniform(-1, 1, m)
        pool.color[start:end] = self.color


class VolumeEmitter(Emitter):
    """体积源：在轴对齐盒内均匀生成（飘雪的空中区域、火焰底部体）。"""

    def __init__(self, center, half_extents, velocity=(0.0, -1.0, 0.0),
                 vel_var=0.2, life_mean=6.0, life_var=1.0,
                 size_mean=0.05, size_var=0.01,
                 color=(0.9, 0.95, 1.0, 0.9),
                 **kwargs) -> None:
        super().__init__(**kwargs)
        self.center = np.asarray(center, dtype=float)
        self.half = np.asarray(half_extents, dtype=float)
        self.velocity = np.asarray(velocity, dtype=float)
        self.vel_var = vel_var
        self.life_mean, self.life_var = life_mean, life_var
        self.size_mean, self.size_var = size_mean, size_var
        self.color = np.asarray(color, dtype=float)

    def _fill(self, pool: ParticlePool, start: int, end: int) -> None:
        m = end - start
        pool.pos[start:end] = self.center + np.random.uniform(
            -1.0, 1.0, size=(m, 3)) * self.half
        pool.prev_pos[start:end] = pool.pos[start:end]
        pool.vel[start:end] = self.velocity + np.random.uniform(
            -self.vel_var, self.vel_var, size=(m, 3))
        pool.acc[start:end] = 0.0
        pool.mass[start:end] = 1.0
        pool.life[start:end] = self.life_mean + \
            self.life_var * np.random.uniform(-1, 1, m)
        pool.max_life[start:end] = pool.life[start:end]
        pool.size[start:end] = self.size_mean + \
            self.size_var * np.random.uniform(-1, 1, m)
        pool.color[start:end] = self.color


class SphereBurstEmitter(Emitter):
    """球面爆炸：一次性向四周均匀发射（烟花爆炸、文字粒子初始爆散）。

    与持续发射器不同：直接给定粒子数，不按 rate×dt。
    """
    def __init__(self, center, speed_mean=8.0, speed_var=1.5,
                 life_mean=1.2, life_var=0.3,
                 size_mean=0.06, size_var=0.01,
                 color=(1.0, 0.6, 0.2, 1.0)) -> None:
        self.center = np.asarray(center, dtype=float)
        self.speed_mean, self.speed_var = speed_mean, speed_var
        self.life_mean, self.life_var = life_mean, life_var
        self.size_mean, self.size_var = size_mean, size_var
        self.color = np.asarray(color, dtype=float)

    def burst(self, pool: ParticlePool, n: int) -> int:
        """一次性发射 n 个粒子，速度方向在球面均匀分布。"""
        start, end = pool.spawn(n)
        if end <= start:
            return 0
        self._fill(pool, start, end)
        return end - start

    def _fill(self, pool: ParticlePool, start: int, end: int) -> None:
        m = end - start
        pool.pos[start:end] = self.center
        pool.prev_pos[start:end] = self.center
        # 球面均匀方向：正态向量归一化
        d = np.random.normal(size=(m, 3))
        d /= np.linalg.norm(d, axis=1, keepdims=True)
        speed = self.speed_mean + self.speed_var * np.random.uniform(-1, 1, m)
        pool.vel[start:end] = speed[:, None] * d
        pool.acc[start:end] = 0.0
        pool.mass[start:end] = 1.0
        pool.life[start:end] = self.life_mean + \
            self.life_var * np.random.uniform(-1, 1, m)
        pool.max_life[start:end] = pool.life[start:end]
        pool.size[start:end] = self.size_mean + \
            self.size_var * np.random.uniform(-1, 1, m)
        pool.color[start:end] = self.color
