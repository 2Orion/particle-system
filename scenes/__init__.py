"""场景包：每个场景 = ParticleSystem 配置 + 逐帧着色/特效回调。

场景只做“配置 + 每帧装饰”（发射器/力/碰撞组合、颜色随生命演化），
物理与渲染完全复用 core/ 与 render/，对应 plan §5“引擎 + 配置”架构。
"""
from .fountain import FountainScene

__all__ = ["FountainScene"]
