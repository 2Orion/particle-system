"""场景基类与统一协议。

场景 = ParticleSystem 配置 + 逐帧着色/特效回调（plan §5"引擎 + 配置"架构）。
物理与渲染全部复用 core/ 与 render/，场景只描述"长什么样"。

子类必须提供：
  name      标题栏显示名
  capacity  粒子池容量
  blend     "additive" 或 "alpha"（决定 GPU 混合模式）
  texture   "gaussian_spot" / "soft_disc" / "ring"
  build()   构造 system 并返回
  shade()   按生命分数更新颜色/尺寸（每帧调用）

可选覆盖：
  update(dt)  默认 = system.update + shade；需要自定义调度（烟花）时覆盖
  reset()     默认 = 重新 build；切换场景时调用
"""
from __future__ import annotations

import numpy as np

from core.system import ParticleSystem

VALID_BLEND = ("additive", "alpha")
VALID_TEXTURE = ("gaussian_spot", "soft_disc", "ring")


def lerp_stops(stops: np.ndarray, frac: np.ndarray) -> np.ndarray:
    """关键帧插值：stops 为 (K,4)，第 0 行对应 frac=1（出生），末行对应 frac=0。

    :param stops: (K,4) RGBA 关键帧，按生命分数从高到低排列
    :param frac: (n,) 生命分数 ∈ [0,1]
    :return: (n,4) 插值后颜色
    """
    t = np.clip((1.0 - np.asarray(frac, dtype=float)) * (len(stops) - 1),
                0.0, len(stops) - 1.0)         # 越界分数先夹紧，再插值
    i0 = np.clip(np.floor(t).astype(int), 0, len(stops) - 2)
    f = (t - i0)[:, None]
    return stops[i0] * (1 - f) + stops[i0 + 1] * f


class Scene:
    """所有场景的基类。"""

    name = "scene"
    capacity = 30_000
    blend = "additive"
    texture = "gaussian_spot"

    def __init__(self) -> None:
        if self.blend not in VALID_BLEND:
            raise ValueError(f"invalid blend mode: {self.blend}")
        if self.texture not in VALID_TEXTURE:
            raise ValueError(f"invalid texture: {self.texture}")
        self.system = self.build()

    # -------------------------------------------------- 子类实现

    def build(self) -> ParticleSystem:
        raise NotImplementedError

    def shade(self) -> None:
        raise NotImplementedError

    # -------------------------------------------------- 通用行为

    def update(self, dt: float) -> dict:
        stats = self.system.update(dt)
        self.shade()
        return stats

    def reset(self) -> None:
        """清空并重建系统（切场景/按 R 重来）。"""
        self.system = self.build()

    @property
    def count(self) -> int:
        return self.system.pool.count
