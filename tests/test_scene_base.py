"""场景协议与基类测试：所有场景共享的契约。"""
import numpy as np
import pytest

from core.system import ParticleSystem
from scenes import SCENE_ORDER, SCENES, Scene
from scenes.base import VALID_TEXTURE, lerp_stops


def test_registry_order_matches_scenes():
    assert set(SCENE_ORDER) == set(SCENES)
    for key in SCENE_ORDER:
        cls = SCENES[key]
        assert issubclass(cls, Scene)


@pytest.mark.parametrize("key", SCENE_ORDER)
def test_scene_contract(key):
    """每个场景都能构造、有合法 blend/texture、可推进且有粒子。"""
    scene = SCENES[key]()
    assert scene.blend in ("additive", "alpha")
    assert scene.texture in VALID_TEXTURE
    assert isinstance(scene.system, ParticleSystem)
    assert scene.capacity > 0
    for _ in range(120):
        scene.update(1 / 60)
    assert 0 < scene.count <= scene.capacity


@pytest.mark.parametrize("key", SCENE_ORDER)
def test_scene_reset_restores_initial_state(key):
    """reset() 重建系统 → 回到刚构造时的状态，且仍可正常运行。

    持续发射类场景初始是空池；prefill 类（文字粒子）初始即已布好粒子。
    """
    cls = SCENES[key]
    initial = cls().count                          # 刚构造时的粒子数
    scene = cls()
    for _ in range(60):
        scene.update(1 / 60)
    assert scene.count > 0
    scene.reset()
    assert scene.count == initial
    if not scene.prefill:
        assert scene.count == 0
    for _ in range(60):
        scene.update(1 / 60)
    assert scene.count > 0


@pytest.mark.parametrize("key", SCENE_ORDER)
def test_scene_no_nan_and_within_killbox(key):
    scene = SCENES[key]()
    for _ in range(240):
        scene.update(1 / 60)
    pool = scene.system.pool
    pos = pool.pos[:pool.count]
    assert np.isfinite(pos).all()
    assert np.isfinite(pool.vel[:pool.count]).all()


@pytest.mark.parametrize("key", SCENE_ORDER)
def test_scene_colors_valid_range(key):
    scene = SCENES[key]()
    for _ in range(120):
        scene.update(1 / 60)
    color = scene.system.pool.color[:scene.count]
    assert color.min() >= -1e-6
    assert color.max() <= 1.0 + 1e-6


def test_invalid_blend_rejected():
    class Bad(Scene):
        name = "bad"
        blend = "screen"

        def build(self):
            return ParticleSystem(capacity=10)

        def shade(self):
            pass

    with pytest.raises(ValueError, match="blend"):
        Bad()


def test_invalid_texture_rejected():
    class Bad(Scene):
        name = "bad"
        blend = "alpha"
        texture = "noise"

        def build(self):
            return ParticleSystem(capacity=10)

        def shade(self):
            pass

    with pytest.raises(ValueError, match="texture"):
        Bad()


# ---------------------------------------------------------------- 关键帧插值

def test_lerp_stops_endpoints():
    stops = np.array([[1.0, 0.0, 0.0, 1.0], [0.0, 0.0, 1.0, 1.0]])
    out = lerp_stops(stops, np.array([1.0, 0.0]))
    assert np.allclose(out[0], stops[0])       # frac=1 → 第 0 帧（出生色）
    assert np.allclose(out[1], stops[-1])      # frac=0 → 末帧（消亡色）


def test_lerp_stops_monotonic_between_two_stops():
    stops = np.array([[1.0, 1.0, 1.0, 1.0], [0.0, 0.0, 0.0, 0.0]])
    frac = np.linspace(0.0, 1.0, 11)
    out = lerp_stops(stops, frac)[:, 0]
    assert np.all(np.diff(out) > -1e-9)        # frac 升 → 值升
    assert np.allclose(out, frac)


def test_lerp_stops_clamps_out_of_range():
    stops = np.array([[1.0, 1.0, 1.0, 1.0], [0.0, 0.0, 0.0, 0.0]])
    out = lerp_stops(stops, np.array([-0.5, 1.5]))
    assert np.all(np.isfinite(out))
    assert np.allclose(out[0], stops[-1])
    assert np.allclose(out[1], stops[0])
