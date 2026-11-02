"""喷泉场景（plan §5）：锥形主喷 + 两侧副喷 + 水面反弹。

物理：重力 + 线性阻力 + 地面碰撞（ε≈0.3 起水花）。
视觉：加法混合高斯光斑；颜色随生命分数 白→浅蓝→深蓝 渐隐
（课件 P19：颜色/透明度是剩余生命的函数）。
"""
from __future__ import annotations

import numpy as np

from core.collisions import KillBox, PlaneCollider
from core.emitters import PointEmitter
from core.forces import Drag, Gravity
from core.system import ParticleSystem

# 水花颜色关键帧：(生命分数, RGB)，线性插值
_COLOR_STOPS = np.array([
    [1.00, 0.95, 0.98, 1.00],   # 出生：近白（高亮水心）
    [0.55, 0.45, 0.70, 1.00],   # 中期：天蓝
    [0.20, 0.15, 0.35, 0.90],   # 后期：深蓝
    [0.00, 0.05, 0.10, 0.40],   # 消亡：暗蓝淡出
])


class FountainScene:
    """中心主喷 + 对称副喷的三联喷泉。"""

    name = "喷泉 Fountain"
    capacity = 30_000

    def __init__(self) -> None:
        self.system = ParticleSystem(capacity=self.capacity,
                                     integrator="velocity_verlet")
        # 主喷：竖直略散
        self.system.emitters.append(PointEmitter(
            origin=(0.0, 0.0, 0.0), direction=(0.0, 1.0, 0.0),
            speed_mean=9.5, speed_var=0.8, angle_var=0.09,
            rate_mean=900, rate_var=150, life_mean=2.2, life_var=0.35,
            size_mean=0.055, size_var=0.012))
        # 两侧副喷：向内倾斜的抛物线拱
        for side in (-1.0, 1.0):
            self.system.emitters.append(PointEmitter(
                origin=(2.2 * side, 0.0, 0.0),
                direction=(-0.45 * side, 1.0, 0.0),
                speed_mean=6.5, speed_var=0.7, angle_var=0.14,
                rate_mean=450, rate_var=80, life_mean=2.0, life_var=0.3,
                size_mean=0.045, size_var=0.010))
        self.system.forces.extend([
            Gravity(g=(0.0, -9.8, 0.0)),
            Drag(k1=0.28),                      # 线性阻力：水花很快达到终端速度
        ])
        self.system.colliders.append(PlaneCollider(
            point=(0, 0, 0), normal=(0, 1, 0),
            restitution=0.30, friction=0.10))   # 落地弹起小水花
        self.system.kill_boxes.append(KillBox(
            lo=(-60, -5, -60), hi=(60, 40, 60)))

    def update(self, dt: float) -> dict:
        stats = self.system.update(dt)
        self._shade()
        return stats

    def _shade(self) -> None:
        """颜色/透明度 = f(生命分数)：水花由亮白转蓝并淡出。"""
        n = self.system.pool.count
        if n == 0:
            return
        frac = self.system.pool.life_fraction          # (n,) ∈ [0,1]
        # 关键帧插值：frac=1 → 第0帧，frac=0 → 末帧
        t = (1.0 - frac) * (len(_COLOR_STOPS) - 1)
        i0 = np.clip(np.floor(t).astype(int), 0, len(_COLOR_STOPS) - 2)
        f = (t - i0)[:, None]
        colors = _COLOR_STOPS[i0] * (1 - f) + _COLOR_STOPS[i0 + 1] * f
        pool = self.system.pool
        pool.color[:n, 0:3] = colors[:, 1:4]            # RGB
        pool.color[:n, 3] = np.clip(frac * 1.4, 0.0, 1.0)  # A：初期即全亮，末期快淡
