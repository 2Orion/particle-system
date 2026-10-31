"""力场：一元力（重力/阻力/风）与环境力（吸引子/排斥子/弹簧阻尼）。

对标课件 P20–25：
- 一元力 unary：重力、粘性阻力、风场
- n 元力 n-ary：弹簧阻尼（particle pair）
- 环境力：吸引子/排斥子

所有力只做“力累加”：直接叠加到 pool.acc（除以质量），整体向量化。
accumulate 回调由 ParticleSystem 提供，签名 accumulate(pool, h)，
内部先清零 acc 再依次调用各力场（积分器可能在步内多次调用，如 velocity verlet）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .pool import ParticlePool


def clear_acc(pool: ParticlePool) -> None:
    pool.acc[:pool.count] = 0.0


# ---------------------------------------------------------------- 一元力

@dataclass
class Gravity:
    """均匀重力场 f = m·g。"""
    g: np.ndarray = field(default_factory=lambda: np.array([0.0, -9.8, 0.0]))

    def apply(self, pool: ParticlePool) -> None:
        n = pool.count
        pool.acc[:n] += self.g


@dataclass
class Drag:
    """粘性阻力：线性 + 平方项组合。

    f = −(k1 + k2·|v|)·v   →   a = −(k1 + k2·|v|)·v
    课件推荐每个粒子至少一点阻力（P24），过度则如糖浆（P21）。
    """
    k1: float = 0.0   # 线性阻力系数（喷泉水花）
    k2: float = 0.0   # 平方阻力系数（烟花下落更真实）

    def apply(self, pool: ParticlePool) -> None:
        if self.k1 == 0.0 and self.k2 == 0.0:
            return
        n = pool.count
        v = pool.vel[:n]
        speed = np.linalg.norm(v, axis=1, keepdims=True)
        pool.acc[:n] -= (self.k1 + self.k2 * speed) * v


@dataclass
class Wind:
    """风场：定常分量 + 多频正弦伪湍流（curl noise 的降级实现，见 plan §10）。

    每粒子相位由位置决定，形成空间上连续、时间上演化的摆动，
    用于雪/火焰。公式：
      w(x,t) = w0 + Σ A_i · sin(ω_i·t + k_i·x + φ_i) · dir_i
    """
    base: np.ndarray = field(default_factory=lambda: np.array([1.0, 0.0, 0.0]))
    amplitude: float = 0.5    # 湍流幅度
    frequency: float = 1.0    # 时间频率 ω
    spatial: float = 0.7      # 空间波数 k
    time: float = 0.0         # 由系统推进

    def apply(self, pool: ParticlePool) -> None:
        n = pool.count
        if self.amplitude == 0.0:
            pool.acc[:n] += self.base
            return
        pos = pool.pos[:n]
        phase = (self.frequency * self.time
                 + self.spatial * (pos[:, 0] + pos[:, 2]))
        turb = self.amplitude * np.sin(phase)[:, None]
        # 湍流分量取垂直于 base 的两个方向，避免与定常风同轴抵消
        b = self.base / (np.linalg.norm(self.base) + 1e-12)
        d1 = np.array([-b[1], b[0], 0.0])
        d1 /= (np.linalg.norm(d1) + 1e-12)
        d2 = np.cross(b, d1)
        pool.acc[:n] += self.base + turb * d1 + 0.5 * self.amplitude * np.sin(1.7 * phase + 1.3)[:, None] * d2


# ---------------------------------------------------------------- 环境力

@dataclass
class Attractor:
    """吸引子（strength<0 为排斥子）：f = s·d / (|d|²+ε)，d 指向中心。"""
    center: np.ndarray = field(default_factory=lambda: np.zeros(3))
    strength: float = 10.0
    softening: float = 0.5

    def apply(self, pool: ParticlePool) -> None:
        n = pool.count
        d = self.center - pool.pos[:n]
        dist2 = np.einsum("ij,ij->i", d, d) + self.softening
        pool.acc[:n] += self.strength * d / dist2[:, None]


@dataclass
class PointSpringDamper:
    """粒子到锚点的弹簧阻尼（n 元力退化为环境力版本，课件 P22–24）。

    f_s = −k_s(|d| − l0)·d̂ ； f_d = −k_d·v
    """
    anchor: np.ndarray = field(default_factory=lambda: np.zeros(3))
    k_s: float = 5.0     # 弹簧刚度
    k_d: float = 1.0     # 阻尼系数
    l0: float = 0.0      # 静止长度

    def apply(self, pool: ParticlePool) -> None:
        n = pool.count
        d = pool.pos[:n] - self.anchor
        dist = np.linalg.norm(d, axis=1, keepdims=True)
        dirv = d / (dist + 1e-12)
        fs = -self.k_s * (dist - self.l0) * dirv
        fd = -self.k_d * pool.vel[:n]
        pool.acc[:n] += fs + fd


@dataclass
class TargetConstraint:
    """软约束（课件 P25）：能量 E = ½k‖C‖²，C = x − x_target。

    f = −∂E/∂x = −k(x − x_target)，加线性阻尼防振荡 —— 文字粒子汇聚用。
    目标点数组形状 (capacity, 3)，仅前 count 个有效。
    """
    targets: np.ndarray          # (capacity, 3)
    k: float = 8.0               # 约束刚度
    damping: float = 2.0         # 阻尼（临界阻尼附近最平滑）

    def apply(self, pool: ParticlePool) -> None:
        n = pool.count
        pool.acc[:n] += -self.k * (pool.pos[:n] - self.targets[:n]) - self.damping * pool.vel[:n]


def accumulate_all(pool: ParticlePool, forces: list) -> None:
    """清零并叠加所有力 → pool.acc（加速度）。质量暂按 1 处理（mass 字段保留）。"""
    clear_acc(pool)
    for f in forces:
        f.apply(pool)
