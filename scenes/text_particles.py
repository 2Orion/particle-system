"""文字/图案粒子场景（plan §5）：软约束汇聚 + 换字重排（morph）。

物理思想完全来自课件 P25 的软约束 / 能量函数：
    E = ½·k·‖C‖²,  C = x − x_target
    f = −∂E/∂x = −k(x − x_target) − c·v      （c 为阻尼，防振荡）
本场景直接用 core.forces.TargetConstraint 实现，逐粒子目标点存在
`TargetConstraint.targets`（(capacity,3) 数组），只取前 count 个有效。

morph 的关键是**让谁去到哪个目标点**：若换字后粒子随机分配目标，
粒子会互相穿越、乱成一团。做法是保留粒子当前顺序，对目标点做
"最近邻贪心配对"的轻量近似——这里用更稳定的做法：
固定的目标点顺序 + 粒子在池内的稳定顺序（compact 保持相对序），
所以 morph 表现为整体流动而非乱窜。

鼠标排斥：鼠标在世界平面（相机 target 所在平面）上的位置投射为一圈排斥源，
用于"扰动文字"，松手后软约束把粒子拉回。
"""
from __future__ import annotations

import numpy as np

from core.collisions import KillBox
from core.emitters import SphereBurstEmitter
from core.forces import Attractor, TargetConstraint
from core.system import ParticleSystem
from scenes.base import Scene
from utils.sampling import text_targets

_COLOR_STOPS = np.array([
    [0.55, 0.85, 1.00, 1.00],   # 新生：青蓝
    [0.75, 0.55, 1.00, 1.00],   # 中期：紫
    [1.00, 0.55, 0.75, 0.85],   # 后期：粉
])


class TextParticlesScene(Scene):
    """粒子汇聚成一段文字。"""

    name = "文字 Text"
    capacity = 12_000
    blend = "additive"
    texture = "gaussian_spot"
    prefill = True        # build() 即布好全部粒子（不靠发射器连续生成）

    # 粒子总数 = 目标点数量（一对一，否则多余的粒子会堆在最后一点上）
    particle_count = 8_000
    default_text = "粒子系统"
    k = 14.0              # 软约束刚度
    damping = 3.6         # 阻尼（临界附近：k=14 时 ≈2√k≈7.5 为欠阻尼，取一半更稳）
    world_height = 3.0
    world_width = 9.0     # 宽度上限：长句子按高度缩放会横向溢出视野
    center_y = 2.2        # 抬离地面，否则文字下半截与 y=0 的网格重叠

    def __init__(self, text: str | None = None) -> None:
        self.text = text or self.default_text
        self._mouse_repeller = None      # build() 之前就存在（reset 也安全）
        super().__init__()

    def build(self) -> ParticleSystem:
        system = ParticleSystem(capacity=self.capacity,
                                integrator="velocity_verlet")
        pts = text_targets(self.text, self.particle_count,
                           world_height=self.world_height,
                           world_width=self.world_width)
        pts[:, 1] += self.center_y
        # targets 覆盖整池容量：多余的槽位复制最后一个点（永不使用）
        targets = np.tile(pts[-1:], (self.capacity, 1))
        targets[:len(pts)] = pts

        self._constraint = TargetConstraint(targets=targets, k=self.k,
                                            damping=self.damping)
        system.forces.append(self._constraint)
        system.kill_boxes.append(KillBox(
            lo=(-30.0, -30.0, -30.0), hi=(30.0, 30.0, 30.0)))

        # 初始状态：从中心球面爆散出发，让软约束把它们拉成文字
        burst = SphereBurstEmitter(center=(0.0, self.center_y, 0.0),
                                   speed_mean=7.0, speed_var=2.0,
                                   life_mean=1e6, life_var=0.0,
                                   size_mean=0.045, size_var=0.012,
                                   color=(0.6, 0.8, 1.0, 1.0))
        burst.burst(system.pool, len(pts))
        # 每个粒子加入轻微的位置抖动与初速度，避免完全重合
        n = system.pool.count
        system.pool.pos[:n] += np.random.uniform(-0.4, 0.4, (n, 3))
        self._mouse_repeller = None      # 新 system 里没有旧的排斥源
        return system

    # -------------------------------------------------- morph

    def set_text(self, text: str) -> None:
        """换字：重采样目标点，粒子在软约束作用下流动重排（morph）。"""
        if not text:
            return
        self.text = text
        n = self.system.pool.count
        if n == 0:
            self.reset()
            return
        pts = text_targets(text, self.particle_count,
                           world_height=self.world_height,
                           world_width=self.world_width)
        pts[:, 1] += self.center_y
        # 目标点数量可能少于粒子数（不同文字覆盖像素不同）：不足的复制末点
        if len(pts) < self.capacity:
            pts = np.vstack([pts, np.tile(pts[-1:], (self.capacity - len(pts), 1))])
        self._constraint.targets[:] = pts[:self.capacity]

    # -------------------------------------------------- 鼠标扰动

    def set_mouse_world(self, point) -> None:
        """鼠标世界坐标 → 排斥源（None 表示离开，撤掉排斥）。"""
        if point is None:
            if self._mouse_repeller is not None:
                # 先判存在再置空（顺序反了会永远删不掉，排斥源残留）
                if self._mouse_repeller in self.system.forces:
                    self.system.forces.remove(self._mouse_repeller)
                self._mouse_repeller = None
            return
        p = np.asarray(point, dtype=float)
        if self._mouse_repeller is None:
            # strength<0 → 排斥；softening 防止近距离力发散（课件 P22 的 ε）
            self._mouse_repeller = Attractor(center=p, strength=-14.0,
                                             softening=0.35)
            self.system.forces.append(self._mouse_repeller)
        else:
            self._mouse_repeller.center = p

    # -------------------------------------------------- 着色

    def shade(self) -> None:
        pool = self.system.pool
        n = pool.count
        if n == 0:
            return
        # 用"离目标多近"代替生命分数：越靠拢越亮（汇聚完成的视觉反馈）
        d = np.linalg.norm(pool.pos[:n] - self._constraint.targets[:n], axis=1)
        settled = np.clip(1.0 - d / 1.5, 0.0, 1.0)[:, None]
        base = _COLOR_STOPS[0][None, :] * (1 - settled) + \
            _COLOR_STOPS[1][None, :] * settled
        pool.color[:n] = base
        pool.color[:n, 3] = 0.35 + 0.6 * settled[:, 0]
        pool.size[:n] = pool.size0[:n] * (1.4 - 0.4 * settled[:, 0])
