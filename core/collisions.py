"""碰撞：平面检测与响应（课件 P42–43）。

检测：当且仅当 N·(P−P0) < 0 时，粒子位于平面负侧（穿入物体）。
响应：v = v_n + v_t → v_new = −ε·v_n + v_t；位置拉回接触点。
课件明确“只需修改粒子的位置和速度”，模拟回退到接触点即可。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .pool import ParticlePool


@dataclass
class PlaneCollider:
    """无限平面碰撞体。

    :param point: 平面上一点 P0。
    :param normal: 法向 N（指向正区，即粒子合法存在的一侧）。
    :param restitution: 回弹系数 ε ∈ [0,1]，0 完全非弹性（积雪），1 完全弹性。
    :param friction: 切向速度衰减系数 ∈ [0,1]，0 无摩擦。
    """
    point: np.ndarray
    normal: np.ndarray
    restitution: float = 0.3
    friction: float = 0.0

    def __post_init__(self) -> None:
        self.point = np.asarray(self.point, dtype=float)
        n = np.asarray(self.normal, dtype=float)
        self.normal = n / np.linalg.norm(n)

    def resolve(self, pool: ParticlePool) -> int:
        """检测并响应所有穿入负区的粒子，返回碰撞数。"""
        n = pool.count
        if n == 0:
            return 0
        pos, vel = pool.pos[:n], pool.vel[:n]
        # 有符号距离 s = N·(P−P0)；s<0 且朝向平面运动(v·N<0)才响应
        s = (pos - self.point) @ self.normal
        hit = (s < 0.0) & (vel @ self.normal < 0.0)
        if not hit.any():
            return 0
        v_hit = vel[hit]
        vn = (v_hit @ self.normal)[:, None] * self.normal[None]
        vt = v_hit - vn
        # 响应：反射法向分量（乘 ε），切向乘 (1−friction)
        v_new = -self.restitution * vn + (1.0 - self.friction) * vt
        vel[hit] = v_new
        # 位置拉回接触点：P ← P − s·N（s<0，故等效于沿法向推回平面）
        pos[hit] -= s[hit][:, None] * self.normal[None]
        # 速度被显式改写，积分器历史（aux）需作废以保持一致
        aux = pool.aux[:n]
        aux[hit] = np.nan
        return int(hit.sum())


@dataclass
class KillBox:
    """世界 AABB 剔除框：粒子离开 [lo, hi] 范围即标记死亡（课件 P18“移走”）。"""
    lo: np.ndarray
    hi: np.ndarray

    def __post_init__(self) -> None:
        self.lo = np.asarray(self.lo, dtype=float)
        self.hi = np.asarray(self.hi, dtype=float)

    def outside(self, pool: ParticlePool) -> np.ndarray:
        """返回越界粒子掩码（True = 已出视域，应删除）。"""
        n = pool.count
        pos = pool.pos[:n]
        return ((pos < self.lo) | (pos > self.hi)).any(axis=1)
