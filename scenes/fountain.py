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
from scenes.base import Scene, lerp_stops

# 水花颜色关键帧：(生命分数, RGB)，线性插值
_COLOR_STOPS = np.array([
    [1.00, 0.97, 1.00, 1.00],   # 出生：近白（高亮水心）
    [0.62, 0.72, 1.00, 1.00],   # 中期：天蓝
    [0.22, 0.34, 0.85, 0.95],   # 后期：深蓝
    [0.08, 0.12, 0.40, 0.45],   # 消亡：暗蓝淡出
])


class FountainScene(Scene):
    """中心主喷 + 对称副喷的三联喷泉。"""

    name = "喷泉 Fountain"
    capacity = 30_000
    blend = "additive"
    texture = "gaussian_spot"

    def build(self) -> ParticleSystem:
        system = ParticleSystem(capacity=self.capacity,
                                integrator="velocity_verlet")
        # 主喷：竖直略散
        system.emitters.append(PointEmitter(
            origin=(0.0, 0.0, 0.0), direction=(0.0, 1.0, 0.0),
            speed_mean=9.5, speed_var=0.8, angle_var=0.075,
            rate_mean=2200, rate_var=300, life_mean=2.2, life_var=0.35,
            size_mean=0.105, size_var=0.022))
        # 两侧副喷：向内倾斜的抛物线拱
        for side in (-1.0, 1.0):
            system.emitters.append(PointEmitter(
                origin=(2.2 * side, 0.0, 0.0),
                direction=(-0.45 * side, 1.0, 0.0),
                speed_mean=6.8, speed_var=0.7, angle_var=0.11,
                rate_mean=1100, rate_var=180, life_mean=2.0, life_var=0.3,
                size_mean=0.095, size_var=0.020))
        system.forces.extend([
            Gravity(g=(0.0, -9.8, 0.0)),
            Drag(k1=0.28),                      # 线性阻力：水花很快达到终端速度
        ])
        system.colliders.append(PlaneCollider(
            point=(0, 0, 0), normal=(0, 1, 0),
            restitution=0.30, friction=0.10))   # 落地弹起小水花
        system.kill_boxes.append(KillBox(
            lo=(-60, -5, -60), hi=(60, 40, 60)))
        return system

    def shade(self) -> None:
        """颜色/透明度 = f(生命分数)：水花由亮白转蓝并淡出。"""
        pool = self.system.pool
        n = pool.count
        if n == 0:
            return
        frac = pool.life_fraction
        colors = lerp_stops(_COLOR_STOPS, frac)
        pool.color[:n, 0:3] = colors[:, 1:4]            # RGB
        pool.color[:n, 3] = np.clip(frac * 1.4, 0.0, 1.0)  # A：初期全亮，末期快淡
