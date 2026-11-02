"""雪场景（plan §5）：大范围飘雪 + 侧向风 + 落地即消。

物理：弱重力 + 平方阻力（雪花终端速度小）+ 多频正弦伪湍流风。
视觉：alpha 混合软圆盘（前后遮挡正确，课件 P40 常规透明混合）；
颜色白蓝，随生命轻微淡出，尺寸在生命周期内略微增大（近处雪花看起来更大）。
"""
from __future__ import annotations

import numpy as np

from core.collisions import KillBox
from core.emitters import VolumeEmitter
from core.forces import Drag, Gravity, Wind
from core.system import ParticleSystem
from scenes.base import Scene, lerp_stops

_COLOR_STOPS = np.array([
    [1.00, 1.00, 1.00, 1.00],   # 出生：纯白
    [0.75, 0.86, 1.00, 0.90],   # 中期：冷白蓝
    [0.60, 0.75, 1.00, 0.55],   # 末期：淡蓝半透明
])


class SnowScene(Scene):
    """全场飘雪。"""

    name = "雪 Snow"
    capacity = 40_000
    blend = "alpha"
    texture = "soft_disc"

    def build(self) -> ParticleSystem:
        system = ParticleSystem(capacity=self.capacity,
                                integrator="velocity_verlet")
        # 高空大盒体积源：雪花在出生时就铺满整个下落区域
        system.emitters.append(VolumeEmitter(
            center=(0.0, 16.0, 0.0), half_extents=(18.0, 9.0, 18.0),
            velocity=(0.0, -1.2, 0.0), vel_var=0.5,
            life_mean=14.0, life_var=2.0,
            size_mean=0.11, size_var=0.035,
            rate_mean=820, rate_var=110))
        system.forces.extend([
            Gravity(g=(0.0, -1.6, 0.0)),        # 弱重力：雪花慢慢飘
            Drag(k1=0.9, k2=0.35),              # 阻力让速度快饱和（终端速度 ≈1.5）
            Wind(base=np.array([0.9, 0.0, 0.35]),
                 amplitude=0.55, frequency=1.1, spatial=0.45),
        ])
        # 落地即消：地面以下剔除（不做弹跳——雪不反弹）
        system.kill_boxes.append(KillBox(
            lo=(-40.0, -0.2, -40.0), hi=(40.0, 30.0, 40.0)))
        return system

    def shade(self) -> None:
        pool = self.system.pool
        n = pool.count
        if n == 0:
            return
        frac = pool.life_fraction
        colors = lerp_stops(_COLOR_STOPS, frac)
        pool.color[:n] = colors
        # 缓慢变大一点点（0.85x → 1.15x），避免生成瞬间的突兀
        pool.size[:n] = pool.size0[:n] * (1.0 - 0.15 * frac)
