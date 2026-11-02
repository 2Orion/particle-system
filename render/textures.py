"""程序化粒子纹理：运行时生成，无外部素材（对应 plan §11“无需外部素材”）。

- gaussian_spot：中心亮、边缘指数衰减的光斑 → 加法混合（烟花/火花/水花）。
  I(r) = exp(−r²/σ²)，课件 P26“把粒子当点光源”的 soft glow。
- soft_disc：平滑圆盘 → alpha 混合（雪花/烟团）。
  alpha(r) = smoothstep(1, 0.75, r)，边缘 0.25 半径内淡出无锯齿。
"""
from __future__ import annotations

import numpy as np


def gaussian_spot(size: int = 64, sigma: float = 0.22) -> np.ndarray:
    """高斯光斑 RGBA，RGB=白（着色时乘粒子色），A=强度。"""
    u = np.linspace(-1.0, 1.0, size)
    r2 = u[:, None] ** 2 + u[None, :] ** 2
    intensity = np.exp(-r2 / (sigma * sigma))
    tex = np.zeros((size, size, 4), dtype=np.float32)
    tex[..., :3] = 1.0
    tex[..., 3] = intensity
    return tex


def soft_disc(size: int = 64, edge: float = 0.25) -> np.ndarray:
    """软圆盘 RGBA：r<1−edge 全不透明，向外 smoothstep 淡出到 0。"""
    u = np.linspace(-1.0, 1.0, size)
    r = np.sqrt(u[:, None] ** 2 + u[None, :] ** 2)
    t = np.clip((1.0 - r) / edge, 0.0, 1.0)
    alpha = t * t * (3.0 - 2.0 * t)  # smoothstep
    tex = np.zeros((size, size, 4), dtype=np.float32)
    tex[..., :3] = 1.0
    tex[..., 3] = alpha
    return tex


def ring(size: int = 64, thickness: float = 0.18) -> np.ndarray:
    """环形纹理（备用：涟漪/环形烟花）。"""
    u = np.linspace(-1.0, 1.0, size)
    r = np.sqrt(u[:, None] ** 2 + u[None, :] ** 2)
    d = np.abs(r - 0.7)
    alpha = np.exp(-(d * d) / (thickness * thickness))
    tex = np.zeros((size, size, 4), dtype=np.float32)
    tex[..., :3] = 1.0
    tex[..., 3] = alpha
    return tex
