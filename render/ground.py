"""地面网格 + 世界坐标轴：线框渲染，给场景提供空间参照。

y=0 平面上的网格线（间隔 grid_step，范围 ±extent）+ 三条坐标轴（RGB=xyz）。
"""
from __future__ import annotations

import numpy as np
import moderngl

from .camera import OrbitCamera

_VERTEX = """
#version 330
in vec3 in_pos;
in vec4 in_color;
uniform mat4 u_mvp;
out vec4 v_color;
void main() {
    gl_Position = u_mvp * vec4(in_pos, 1.0);
    v_color = in_color;
}
"""

_FRAGMENT = """
#version 330
in vec4 v_color;
out vec4 fragColor;
void main() { fragColor = v_color; }
"""


class GridRenderer:
    """静态网格 + 坐标轴，一次构建，每帧仅换 MVP。"""

    GRID_COLOR = (0.30, 0.33, 0.38, 0.5)
    AXIS_X = (0.85, 0.30, 0.30, 0.9)
    AXIS_Y = (0.30, 0.85, 0.30, 0.9)
    AXIS_Z = (0.30, 0.45, 0.90, 0.9)

    def __init__(self, ctx: moderngl.Context, extent: float = 30.0,
                 grid_step: float = 1.0, axis_len: float = 2.0) -> None:
        self.ctx = ctx
        self.extent = float(extent)      # main.py 切场景时据此判断是否需重建
        self.prog = ctx.program(vertex_shader=_VERTEX, fragment_shader=_FRAGMENT)
        verts, colors = self._build(extent, grid_step, axis_len)
        self._vbo = ctx.buffer(np.hstack([verts, colors]).astype("f4").tobytes())
        self._vao = ctx.vertex_array(self.prog, [(self._vbo, "3f 4f", "in_pos", "in_color")])
        self._count = len(verts)

    @staticmethod
    def _build(extent: float, step: float, axis_len: float):
        verts, colors = [], []
        # 网格线：平行 x 与 z 的两组
        i = -extent
        while i <= extent:
            x_col = np.allclose(abs(i) % max(step * 5, 1e-9), 0, atol=1e-6) or abs(i) < 1e-6
            color = (*GridRenderer.GRID_COLOR[:3], 0.7) if x_col else GridRenderer.GRID_COLOR
            if abs(i) < 1e-6:
                color = (0.42, 0.42, 0.48, 0.8)  # 主轴线稍亮
            verts += [[i, 0.0, -extent], [i, 0.0, extent]]
            colors += [color, color]
            verts += [[-extent, 0.0, i], [extent, 0.0, i]]
            colors += [color, color]
            i += step
        # 坐标轴（略抬高避免与网格 z-fighting）
        eps = 0.002
        for direction, color in (((1, 0, 0), GridRenderer.AXIS_X),
                                 ((0, 1, 0), GridRenderer.AXIS_Y),
                                 ((0, 0, 1), GridRenderer.AXIS_Z)):
            d = np.asarray(direction, dtype=float)
            verts += [d * eps, d * axis_len]
            colors += [color, color]
        return np.array(verts, dtype=np.float32), np.array(colors, dtype=np.float32)

    def render(self, camera: OrbitCamera, viewport: tuple[int, int]) -> None:
        w, h = viewport
        self.prog["u_mvp"].write(camera.mvp(w / h).T.astype("f4").tobytes())
        self.ctx.enable(moderngl.BLEND)
        self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        self.ctx.enable(moderngl.DEPTH_TEST)
        self._vao.render(moderngl.LINES)
        self.ctx.disable(moderngl.BLEND)

    def release(self) -> None:
        self._vbo.release()
        self._vao.release()
