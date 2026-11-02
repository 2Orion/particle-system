"""粒子数据池：SoA（Structure of Arrays）布局 + 压缩式存亡管理。

设计要点：
- 所有属性存为 NumPy 数组（课件 ``struct Particle`` 的 SoA 版本），
  活粒子始终压缩在 ``[0, count)`` 区间，便于整体向量化运算；
- ``spawn()`` 返回连续索引区间，发射器直接切片填充属性（O(1)，无内存分配）；
- ``compact(alive)`` 按布尔掩码删除死亡粒子（对应课件"粒子消亡"三情形的载体）；
- ``aux`` 为积分器附加状态（Leap-Frog 的半步速度），
  同时兼作"新粒子/状态失效"标记：``NaN`` 表示需要积分器做首步初始化
  或碰撞后重置。
"""
from __future__ import annotations

import numpy as np


class ParticlePool:
    """定容粒子池。属性字段与课件 Particle 结构对应。"""

    __slots__ = (
        "capacity", "count",
        "pos", "prev_pos", "vel", "acc", "aux",
        "mass", "life", "max_life", "size", "size0", "color",
    )

    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.capacity = int(capacity)
        self.count = 0
        n = self.capacity
        self.pos = np.zeros((n, 3))          # 当前位置
        self.prev_pos = np.zeros((n, 3))     # 上一位置（Verlet 用）
        self.vel = np.zeros((n, 3))          # 速度
        self.acc = np.zeros((n, 3))          # 加速度（力累加后除以质量）
        self.aux = np.full((n, 3), np.nan)   # 积分器附加状态；NaN=待初始化
        self.mass = np.ones(n)               # 质量
        self.life = np.zeros(n)              # 剩余生命周期（秒），<=0 死亡
        self.max_life = np.ones(n)           # 初始生命周期（用于生命分数）
        self.size = np.ones(n)               # 绘制尺寸（场景可逐帧改写）
        self.size0 = np.ones(n)              # 出生尺寸（逐帧缩放时作基准）
        self.color = np.zeros((n, 4))        # RGBA

    def spawn(self, n: int) -> tuple[int, int]:
        """申请 n 个新粒子，返回索引区间 [start, end)。

        超出容量时截断（返回区间长度可能小于 n）。
        新粒子属性未初始化，调用方应立即填充；``aux`` 置 NaN 标记待初始化。
        """
        n = min(int(n), self.capacity - self.count)
        if n <= 0:
            return self.count, self.count
        start, end = self.count, self.count + n
        self.count = end
        self.aux[start:end] = np.nan
        return start, end

    def compact(self, alive: np.ndarray) -> int:
        """按存活掩码删除死亡粒子，活粒子压缩到前段。

        :param alive: 形状为 (count,) 的布尔数组，True 表示存活。
        :return: 删除的粒子数。
        """
        alive = np.asarray(alive, dtype=bool)
        if alive.shape != (self.count,):
            raise ValueError(f"alive mask shape {alive.shape} != ({self.count},)")
        dead = int(self.count - alive.sum())
        if dead:
            for name in self.__slots__:
                if name in ("capacity", "count"):
                    continue
                arr = getattr(self, name)
                kept = arr[:self.count][alive]
                arr[:len(kept)] = kept
            self.count -= dead
        return dead

    @property
    def life_fraction(self) -> np.ndarray:
        """生命分数 life/max_life ∈ [0,1]，颜色/尺寸随生命变化用。"""
        return self.life[:self.count] / self.max_life[:self.count]
