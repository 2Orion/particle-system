"""火焰场景（plan §5）：底部体积源 + 浮力 + 伪湍流 + 黄→橙→红→灰烬渐变。

物理：浮力（随生命衰减，见 core.forces.Buoyancy）+ 弱重力 + 阻力 + 风。
视觉：加法混合软圆盘；颜色随生命 亮黄→橙→暗红→灰，尺寸随生命收缩，
整体呈"上宽下窄再散开"的火舌形态。
"""
from __future__ import annotations

import numpy as np

from core.collisions import KillBox
from core.emitters import VolumeEmitter
from core.forces import Buoyancy, Drag, Gravity, Wind
from core.system import ParticleSystem
from scenes.base import Scene, lerp_stops

# 加法混合会累加亮度：单粒子颜色需压暗，否则密集处全部 clip 成白色
_COLOR_STOPS = np.array([
    [1.00, 0.72, 0.20, 0.42],   # 出生：亮的火心
    [0.92, 0.34, 0.05, 0.34],   # 中期：橙色
    [0.55, 0.09, 0.02, 0.24],   # 后期：暗红
    [0.06, 0.05, 0.05, 0.05],   # 消亡：灰烬淡出
])


class FireScene(Scene):
    """底部燃烧的火堆。"""

    name = "火焰 Fire"
    capacity = 25_000
    blend = "additive"
    texture = "soft_disc"

    def build(self) -> ParticleSystem:
        system = ParticleSystem(capacity=self.capacity,
                                integrator="velocity_verlet")
        # 火源：贴地扁盒子，向上喷出
        system.emitters.append(VolumeEmitter(
            center=(0.0, 0.15, 0.0), half_extents=(0.55, 0.12, 0.55),
            velocity=(0.0, 2.4, 0.0), vel_var=0.9,
            life_mean=1.7, life_var=0.35,
            size_mean=0.16, size_var=0.05,
            rate_mean=1100, rate_var=180))
        system.forces.extend([
            Buoyancy(acceleration=9.5),         # 浮力：火舌上升的主因
            Gravity(g=(0.0, -1.2, 0.0)),        # 微弱重力，让火焰略微收束
            Drag(k1=1.5, k2=0.35),              # 阻力：上升速度封顶 ≈6 m/s
            Wind(base=np.array([0.0, 0.0, 0.0]),
                 amplitude=2.2, frequency=1.9, spatial=1.4),  # 横向摆动撕开火舌
        ])
        system.kill_boxes.append(KillBox(
            lo=(-20.0, -0.5, -20.0), hi=(20.0, 16.0, 20.0)))
        return system

    def shade(self) -> None:
        pool = self.system.pool
        n = pool.count
        if n == 0:
            return
        frac = pool.life_fraction
        colors = lerp_stops(_COLOR_STOPS, frac)
        pool.color[:n] = colors
        # 尺寸随生命收缩到 20%：火焰尖端收尖
        pool.size[:n] = pool.size0[:n] * (0.20 + 0.80 * frac)
