"""烟花场景（plan §5）：火箭升空 → 顶点炸开 → 火星下落熄灭。

调度设计：火箭不是池内粒子，而是场景持有的一个解析弹道对象
（pos/vel 按匀速重力闭式更新）。原因：pool.compact() 会重排粒子，
用索引跟踪"哪颗是火箭"不可靠；把火箭放在池外，池里只放可见的火星，
既简单又不会因压缩而错位。

轨迹（trail）：每帧在火箭当前位置补几颗短命小火星，形成上升光尾。
炸开（burst）：火箭速度竖直分量 ≤0（或引信到期）时，
在其位置调用 SphereBurstEmitter 一次性向球面均匀喷射。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from core.collisions import KillBox
from core.emitters import SphereBurstEmitter
from core.forces import Drag, Gravity
from core.system import ParticleSystem
from scenes.base import Scene

# 每发烟花的配色（RGB），加法混合下越叠越亮
_PALETTE = np.array([
    [1.00, 0.85, 0.30],   # 金
    [1.00, 0.30, 0.35],   # 红
    [0.40, 0.85, 1.00],   # 青
    [0.75, 0.40, 1.00],   # 紫
    [0.45, 1.00, 0.55],   # 绿
])

_GRAVITY = np.array([0.0, -9.8, 0.0])


@dataclass
class Rocket:
    """解析弹道的火箭弹（池外对象）。"""
    pos: np.ndarray
    vel: np.ndarray
    color: np.ndarray
    burst_count: int = 1100
    speed_mean: float = 12.5
    speed_var: float = 2.5
    fuse: float = 10.0                 # 保险引信（秒），防止火箭永不落顶

    def step(self, dt: float) -> None:
        """匀加速弹道：v += g·dt, x += v·dt（半隐式，稳定且与池内积分器同量级）。"""
        self.vel = self.vel + _GRAVITY * dt
        self.pos = self.pos + self.vel * dt
        self.fuse -= dt

    @property
    def apex(self) -> bool:
        """到达顶点：竖直速度已 ≤0（开始下落）。"""
        return self.vel[1] <= 0.0 or self.fuse <= 0.0


class FireworksScene(Scene):
    """连续放烟花的夜空。"""

    name = "烟花 Fireworks"
    capacity = 60_000
    blend = "additive"
    texture = "gaussian_spot"

    # 发射节奏（秒）——子类/测试可调
    launch_interval = 0.7
    max_rockets = 5

    def __init__(self, auto_launch: bool = True) -> None:
        self.auto_launch = auto_launch
        super().__init__()

    def build(self) -> ParticleSystem:
        system = ParticleSystem(capacity=self.capacity,
                                integrator="velocity_verlet")
        # 池内无持续发射器：火星全部由 burst/trail 直接注入
        system.forces.extend([
            Gravity(g=(0.0, -9.8, 0.0)),
            Drag(k2=0.12),                  # 平方阻力：火星下落减速更真实
        ])
        system.kill_boxes.append(KillBox(
            lo=(-80.0, 0.0, -80.0), hi=(80.0, 60.0, 80.0)))
        self._rockets: list[Rocket] = []
        self._launch_timer = 0.0
        self._color_cursor = 0
        return system

    # -------------------------------------------------- 调度

    def launch(self, origin=None) -> Rocket:
        """发射一发火箭弹（默认从地面随机位置向上）。"""
        if origin is None:
            origin = np.array([np.random.uniform(-6.0, 6.0),
                               np.random.uniform(-3.0, -1.0),
                               np.random.uniform(-3.0, 3.0)])
        vel = np.array([np.random.uniform(-0.8, 0.8),
                        np.random.uniform(15.0, 18.0),
                        np.random.uniform(-0.8, 0.8)])
        color = _PALETTE[self._color_cursor % len(_PALETTE)]
        self._color_cursor += 1
        rocket = Rocket(pos=np.asarray(origin, dtype=float),
                        vel=vel, color=color.copy())
        self._rockets.append(rocket)
        return rocket

    def _spawn_trail(self, rocket: Rocket) -> None:
        """在当前火箭位置补一小簇短命火星（上升光尾）。"""
        emitter = SphereBurstEmitter(
            center=rocket.pos, speed_mean=1.2, speed_var=0.6,
            life_mean=0.45, life_var=0.12,
            size_mean=0.09, size_var=0.025,
            color=(0.85 * rocket.color[0], 0.62 * rocket.color[1],
                   0.30 * rocket.color[2], 1.0))
        emitter.burst(self.system.pool, 14)

    def _burst(self, rocket: Rocket) -> None:
        """在火箭位置炸开一团球面火星。"""
        emitter = SphereBurstEmitter(
            center=rocket.pos, speed_mean=rocket.speed_mean,
            speed_var=rocket.speed_var,
            life_mean=2.6, life_var=0.6,
            size_mean=0.24, size_var=0.07,
            color=(rocket.color[0], rocket.color[1], rocket.color[2], 1.0))
        emitter.burst(self.system.pool, rocket.burst_count)

    def update(self, dt: float) -> dict:
        """推进一帧：定时发射 → 更新火箭并炸开 → 池物理 → 着色。"""
        dt = max(0.0, float(dt))
        if self.auto_launch:
            self._launch_timer -= dt
            while self._launch_timer <= 0.0 and len(self._rockets) < self.max_rockets:
                self.launch()
                self._launch_timer += self.launch_interval * np.random.uniform(0.7, 1.3)

        # 火箭推进：先补轨迹，到顶点则炸开
        still_airborne = []
        for r in self._rockets:
            r.step(dt)
            if r.apex:
                self._burst(r)
            else:
                self._spawn_trail(r)
                still_airborne.append(r)
        self._rockets = still_airborne

        stats = self.system.update(dt)
        self.shade()
        stats["rockets"] = len(self._rockets)
        return stats

    def reset(self) -> None:
        self.system = self.build()

    # -------------------------------------------------- 着色

    def shade(self) -> None:
        """只调透明度：RGB 保留每发烟花自己的配色（加法混合亮度=强度）。"""
        pool = self.system.pool
        n = pool.count
        if n == 0:
            return
        frac = pool.life_fraction
        pool.color[:n, 3] = np.clip(frac * 1.5, 0.0, 1.0)
