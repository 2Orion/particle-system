"""粒子系统：课件 P12 五步循环的调度器，P59 ParticleSystem 类的项目版。

每帧步骤：
  1. 生成新粒子并加入系统        emitters.emit()
  2. 赋予每一新粒子属性          emitter._fill()（mean+variance）
  3. 删除超过生命周期的粒子      pool.compact(alive)（寿命/淡出/移走）
  4. 根据动态属性移动和变换粒子  integrator.step()（固定步长 accumulator）
  5. 绘制并显示                  渲染层职责（本轮不实现）

物理更新与渲染帧率解耦：update(dt) 累积时间，按固定步长 h 步进。
"""
from __future__ import annotations

import numpy as np

from .collisions import KillBox, PlaneCollider
from .emitters import Emitter
from .forces import Wind, accumulate_all
from .integrators import INTEGRATORS, compute_vel, repair_verlet_history
from .pool import ParticlePool


class ParticleSystem:
    """发射器 + 力场 + 积分器 + 碰撞体的组合，驱动一个 ParticlePool。"""

    def __init__(self, capacity: int = 100_000,
                 integrator: str = "velocity_verlet",
                 fixed_step: float = 1.0 / 120.0,
                 max_substeps: int = 8) -> None:
        self.pool = ParticlePool(capacity)
        self.emitters: list[Emitter] = []
        self.forces: list = []
        self.colliders: list[PlaneCollider] = []
        self.kill_boxes: list[KillBox] = []
        if integrator not in INTEGRATORS:
            raise ValueError(f"unknown integrator: {integrator!r}, "
                             f"expected one of {sorted(INTEGRATORS)}")
        self.integrator_name = integrator
        self.integrator = INTEGRATORS[integrator]
        self.fixed_step = fixed_step
        self.max_substeps = max_substeps
        self.time = 0.0
        self._accumulator = 0.0
        # 风场引用缓存（构造后 forces 变更时调用 refresh_wind()，首帧惰性刷新）
        self._wind: list[Wind] | None = None

    def refresh_wind(self) -> None:
        """forces 列表变更后刷新风场引用（update 每帧推进其 time）。"""
        self._wind = [f for f in self.forces if isinstance(f, Wind)]

    def set_integrator(self, name: str) -> None:
        """切换积分器（唯一的切换入口，务必走这里而不是直接改字段）。

        ``pool.aux`` 是四种积分器共用的一格附加状态，但语义各不相同：
        verlet 存「上一步位置 xₙ₋₁」、leapfrog 存「半步速度 vₜ₋ₕ/₂」、
        euler 恒置 0、velocity_verlet 不写。新旧积分器之间这些值不可兼容，
        直接切过去会拿别人的数据当自己的用 —— 例如 verlet 用
        ``2xₙ − aux`` 推进，而 aux 还是 0 时位置会瞬间翻倍，等于注入一个
        ``x/h`` 的伪速度，粒子随即飞出 KillBox 被永久删除。

        所以切换时把 aux 整体置 NaN（与 ``spawn()`` 同一个哨兵约定），
        让新积分器在下一步对全部粒子做首步初始化。
        """
        if name not in INTEGRATORS:
            raise ValueError(f"unknown integrator: {name!r}, "
                             f"expected one of {sorted(INTEGRATORS)}")
        if name == self.integrator_name:
            return
        self.pool.aux[:self.pool.count] = np.nan
        self.integrator_name = name
        self.integrator = INTEGRATORS[name]

    # -------------------------------------------------- 帧循环

    def _accumulate(self, pool: ParticlePool, h: float) -> None:
        """积分器回调：叠加当前力到 acc。风场时间随子步推进。"""
        if self._wind is None:
            self.refresh_wind()
        for w in self._wind:
            w.time = self.time
        accumulate_all(pool, self.forces)

    def step_physics(self, h: float) -> None:
        """单个固定物理步：力 → 积分 → 碰撞响应。"""
        if self.integrator_name == "verlet":
            # 兜底校验 aux：切积分器走 set_integrator 已经作废过，但脚本/
            # 未来代码仍可能绕过它直接改字段。必须在 compute_vel 之前调用。
            repair_verlet_history(self.pool, h)
        self.integrator(self.pool, h, self._accumulate)
        if self.integrator_name == "verlet":
            compute_vel(self.pool, h)
        for c in self.colliders:
            c.resolve(self.pool)
        self.time += h

    def update(self, dt: float, area_factor: float = 1.0) -> dict:
        """推进一帧：发射 → 寿命衰减 → 固定步长物理 → 剔除。

        :param dt: 帧时间（秒）。
        :param area_factor: 发射面积因子 A（屏幕面积自适应，渲染层可选提供）。
        :return: 帧统计（发射数、死亡数、粒子数等）。
        """
        dt = max(0.0, dt)
        stats = {"emitted": 0, "died": 0, "alive": 0, "collisions": 0}

        # 1+2. 发射并初始化（首帧惰性刷新风场引用）
        if self._wind is None:
            self.refresh_wind()
        for e in self.emitters:
            stats["emitted"] += e.emit(self.pool, dt, area_factor)

        # 3a. 寿命衰减：每帧 life -= dt（课件 P16“每帧减 1”的连续版）
        n = self.pool.count
        if n:
            self.pool.life[:n] -= dt

        # 4. 固定步长物理（步数一次算出，避免循环减法的浮点漂移）
        self._accumulator += dt
        h = self.fixed_step
        steps = min(int(self._accumulator / h), self.max_substeps)
        for _ in range(steps):
            self.step_physics(h)
        self._accumulator -= steps * h
        if steps == self.max_substeps:
            self._accumulator = 0.0  # 防螺旋：丢弃积压时间

        # 3b. 判死：寿命尽 / 出界
        n = self.pool.count
        if n:
            alive = self.pool.life[:n] > 0.0
            for kb in self.kill_boxes:
                alive &= ~kb.outside(self.pool)
            # 快路径：全活时跳过 compact 的全字段重排（稳态下几乎不触发，
            # 一旦有死亡才真正压缩，避免每帧 O(字段数 × count) 的拷贝）
            if not alive.all():
                stats["died"] = self.pool.compact(alive)
        stats["alive"] = self.pool.count
        return stats
