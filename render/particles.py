"""粒子渲染器：GPU 点精灵（GL 3.3），两种混合模式（课件 P26/P40）。

- additive：glBlendFunc(SRC_ALPHA, ONE) —— 叠加越多数越亮（点光源模型，
  FinalColor = Dest + Src·SrcAlpha，对应课件 P40 加法混合公式）。
- alpha：glBlendFunc(SRC_ALPHA, ONE_MINUS_SRC_ALPHA) —— 常规透明混合
  （雪花/烟团，前后遮挡）。

点大小：gl_PointSize = size_world · pixels_per_unit / dist（透视缩放），
clamp 到 [1, max_point_size]（驱动上限常见 63~255，构造时查询）。
"""
from __future__ import annotations

import numpy as np
import moderngl

from core.pool import ParticlePool
from render.camera import OrbitCamera
from render.textures import gaussian_spot, soft_disc

_VERTEX = """
#version 330
in vec3 in_pos;      // 世界位置
in vec4 in_color;    // 粒子 RGBA（alpha=不透明度）
in float in_size;    // 世界尺寸（半径）

uniform mat4 u_mvp;
uniform float u_pixels_per_unit;  // 世界单位→像素（在视口高上）
uniform float u_point_scale;      // 纹理有效半径补偿（默认 1）

out vec4 v_color;

void main() {
    gl_Position = u_mvp * vec4(in_pos, 1.0);
    float dist = max(gl_Position.w, 1e-4);          // 透视深度（视图空间 −z = w）
    gl_PointSize = clamp(in_size * u_pixels_per_unit * u_point_scale / dist,
                         1.0, u_max_point_size);
    v_color = in_color;
}
"""

_FRAGMENT = """
#version 330
uniform sampler2D u_texture;
in vec4 v_color;
out vec4 fragColor;

void main() {
    vec2 uv = gl_PointCoord * 2.0 - 1.0;           // [−1,1]²
    vec4 texel = texture(u_texture, gl_PointCoord);
    fragColor = vec4(v_color.rgb, v_color.a * texel.a);
}
"""

# u_max_point_size 需要 uniform 声明 —— 合入顶点着色器
_VERTEX = _VERTEX.replace("uniform float u_point_scale;",
                          "uniform float u_point_scale;\nuniform float u_max_point_size;")


class ParticleRenderer:
    """把 ParticlePool 的活粒子区间上传 GPU 并绘制点精灵。"""

    def __init__(self, ctx: moderngl.Context, max_particles: int,
                 blend: str = "additive") -> None:
        if blend not in ("additive", "alpha"):
            raise ValueError(f"unknown blend mode: {blend}")
        self.ctx = ctx
        self.blend = blend
        self.max_particles = max_particles
        self._vertexarray = None
        self._buffer = None
        self.prog = ctx.program(vertex_shader=_VERTEX, fragment_shader=_FRAGMENT)
        # GL_POINT_SIZE_RANGE：不同驱动返回 str 或 tuple，取上界
        psr = ctx.info.get("GL_POINT_SIZE_RANGE", (1.0, 63.0))
        self.max_point_size = float(psr[-1] if isinstance(psr, tuple) else str(psr).split()[-1])
        # 纹理（惰性创建，可换）
        self.texture = self._make_texture(gaussian_spot())
        self._setup_buffer(max_particles)

    def _make_texture(self, data: np.ndarray) -> moderngl.Texture:
        tex = self.ctx.texture((data.shape[0], data.shape[1]), 4,
                               data.tobytes(), dtype="f4")
        tex.build_mipmaps()
        tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        return tex

    def set_texture(self, data: np.ndarray) -> None:
        """更换粒子纹理（gaussian_spot / soft_disc / ring）。"""
        if self.texture is not None:
            self.texture.release()
        self.texture = self._make_texture(data)

    def _setup_buffer(self, max_particles: int) -> None:
        # 交错布局：pos(3) color(4) size(1) = 8 floats
        stride = 8 * 4
        if self._buffer:
            self._buffer.release()
            self._vertexarray = None
        self._buffer = self.ctx.buffer(reserve=max_particles * stride)
        vao_content = [
            (self._buffer, "3f 4f 1f", "in_pos", "in_color", "in_size"),
        ]
        self._vertexarray = self.ctx.vertex_array(self.prog, vao_content)

    def render(self, pool: ParticlePool, camera: OrbitCamera,
               viewport: tuple[int, int], global_alpha: float = 1.0) -> None:
        """上传活粒子并绘制。viewport=(w,h) 用于算 pixels_per_unit 与 alpha 衰减。"""
        n = pool.count
        if n == 0:
            return
        # 交错打包：float32 一份拷贝（GPU 上传必需）
        data = np.empty((n, 8), dtype=np.float32)
        data[:, 0:3] = pool.pos[:n]
        data[:, 3:7] = pool.color[:n]
        data[:, 3:6] *= pool.color[:n, 3:4]  # 颜色乘自身 alpha（加法混合亮度即强度）
        data[:, 7] = pool.size[:n]
        self._buffer.write(data.tobytes())

        w, h = viewport
        self.prog["u_mvp"].write(camera.mvp(w / h).T.astype("f4").tobytes())
        self.prog["u_pixels_per_unit"].value = camera.pixels_per_unit(h)
        self.prog["u_point_scale"].value = 2.0  # size=半径，点精灵直径=2r
        self.prog["u_max_point_size"].value = self.max_point_size
        self.texture.use(0)

        self.ctx.enable(moderngl.PROGRAM_POINT_SIZE)
        if self.blend == "additive":
            self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE
        else:
            self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        self.ctx.enable(moderngl.BLEND)
        self.ctx.disable(moderngl.DEPTH_TEST)  # 粒子按绘制顺序混合，不写深度
        self._vertexarray.render(moderngl.POINTS, vertices=n)
        self.ctx.disable(moderngl.BLEND)
        self.ctx.disable(moderngl.PROGRAM_POINT_SIZE)
