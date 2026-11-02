"""场景包：每个场景 = ParticleSystem 配置 + 逐帧着色/特效回调。

场景只做"配置 + 每帧装饰"（发射器/力/碰撞组合、颜色随生命演化），
物理与渲染完全复用 core/ 与 render/，对应 plan §5"引擎 + 配置"架构。
"""
from .base import Scene
from .fire import FireScene
from .fireworks import FireworksScene
from .fountain import FountainScene
from .snow import SnowScene

# 场景注册表：main.py 按数字键 1..N 切换
SCENES: dict[str, type[Scene]] = {
    "fountain": FountainScene,
    "snow": SnowScene,
    "fire": FireScene,
    "fireworks": FireworksScene,
}
SCENE_ORDER = ["fountain", "snow", "fire", "fireworks"]

__all__ = [
    "Scene", "SCENES", "SCENE_ORDER",
    "FountainScene", "SnowScene", "FireScene", "FireworksScene",
]
