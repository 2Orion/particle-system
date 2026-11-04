"""文字/图案 → 3D 目标点云采样（plan §5 文字粒子场景的素材生成）。

流程：Pillow 把文字渲染成灰度位图 → 阈值化 → 取亮像素坐标 → 归一化到
世界坐标（居中、高度约 2 个世界单位）→ 上采样到需要数量的粒子。

采样策略（顺序很重要，决定汇聚效果是否均匀）：
1. 取所有亮像素坐标，按行优先顺序（保证同一文字每次采样结果稳定）；
2. 若亮像素数 ≥ 目标粒子数，用**系统抽样**（等间隔取）而非随机抽，
   避免同一目标点被多个粒子重复占用导致局部空缺；
3. 若亮像素数 < 目标粒子数，对已有坐标做子像素抖动复制。

不排名也不依赖 PIL 字体以外的东西；字体缺失时退回默认字体。
"""
from __future__ import annotations

import pathlib

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Windows 常见中文字体候选；按顺序尝试，都没有则用 Pillow 默认字体
_CJK_FONT_CANDIDATES = (
    "C:/Windows/Fonts/msyhbd.ttc",       # 微软雅黑 Bold
    "C:/Windows/Fonts/msyh.ttc",         # 微软雅黑
    "C:/Windows/Fonts/simhei.ttf",       # 黑体
    "C:/Windows/Fonts/arialbd.ttf",      # Arial Bold（无中文）
)


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in _CJK_FONT_CANDIDATES:
        if pathlib.Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def render_text_mask(text: str, canvas: int = 512, font_size: int = 280,
                     threshold: int = 128, margin: int = 12) -> np.ndarray:
    """把文字渲染成布尔掩膜（True = 属于文字笔画）。

    :param text: 文本内容（支持中文，依赖系统字体）
    :param canvas: 正方形画布边长（像素）
    :param font_size: 初始字号；放不下时自动缩小
    :param threshold: 灰度阈值（>threshold 视为笔画）
    :param margin: 边距，避免笔画贴边
    :return: (canvas, canvas) bool 数组，行 0 为图像顶部
    """
    if not text:
        return np.zeros((canvas, canvas), dtype=bool)

    size = font_size
    while size > 8:
        font = _load_font(size)
        img = Image.new("L", (canvas, canvas), 0)
        draw = ImageDraw.Draw(img)
        l, t, r, b = draw.textbbox((0, 0), text, font=font)
        w, h = r - l, b - t
        if w <= canvas - 2 * margin and h <= canvas - 2 * margin:
            draw.text((margin - l + (canvas - 2 * margin - w) // 2,
                       margin - t + (canvas - 2 * margin - h) // 2),
                      text, font=font, fill=255)
            return np.asarray(img) > threshold
        size = int(size * 0.85)

    return np.zeros((canvas, canvas), dtype=bool)


def mask_to_points(mask: np.ndarray, world_height: float = 3.0,
                   z_spread: float = 0.0,
                   world_width: float | None = None) -> np.ndarray:
    """掩膜 → 世界坐标点云（居中于原点，y 向上，位于 z=0 平面）。

    :param mask: (H, W) bool 数组，行 0 为顶部
    :param world_height: 文字在世界空间的高度（y 方向跨度）
    :param z_spread: 可选的 z 向随机厚度（>0 时成为 3D 云团而非平面）
    :param world_width: 可选的宽度上限；长句子只按高度缩放会横向溢出视野，
        所以实际缩放取 min(高度尺度, 宽度尺度) —— 横向装不下时整体缩小。
    :return: (N, 3) float64
    """
    rows, cols = np.nonzero(mask)               # 行优先，确定性强
    if len(rows) == 0:
        return np.zeros((0, 3))

    # 按笔画**实际包围盒**缩放（画布留白不该算进 world_height，
    # 否则一行文字的 y 跨度只有画布的零头，字会缩在中心一小块）
    r0, r1 = rows.min(), rows.max()
    c0, c1 = cols.min(), cols.max()
    glyph_h = max(r1 - r0 + 1, 1)
    scale = world_height / glyph_h
    if world_width is not None:
        glyph_w = max(c1 - c0 + 1, 1)
        scale = min(scale, world_width / glyph_w)
    cx = (c0 + c1) / 2.0
    cy = (r0 + r1) / 2.0
    # 图像 y 向下 → 世界 y 向上；以笔画中心为原点居中
    x = (cols - cx) * scale
    y = (cy - rows) * scale
    pts = np.column_stack([x, y, np.zeros(len(x))])
    if z_spread > 0.0:
        pts[:, 2] = np.random.uniform(-z_spread, z_spread, len(pts))
    return pts


def sample_points(points: np.ndarray, n: int) -> np.ndarray:
    """把点云重采样为恰好 n 个目标点。

    - n ≤ 原点数：系统抽样（等间隔），保证覆盖均匀、结果稳定；
    - n > 原点数：整除复制后余数部分随机挑，并加亚像素抖动打散重叠。
    """
    if n <= 0:
        return np.zeros((0, 3))
    if len(points) == 0:
        return np.zeros((n, 3))

    if n <= len(points):
        idx = np.linspace(0, len(points) - 1, n).astype(int)
        return points[idx].copy()

    reps = int(np.ceil(n / len(points)))
    base = np.tile(points, (reps, 1))[:n].copy()
    # 亚像素抖动：避免多个粒子完全重合（重合会看得见"点"而不是"笔画"）
    jitter = np.random.uniform(-0.004, 0.004, base.shape)
    return base + jitter


def text_targets(text: str, n: int, canvas: int = 512, font_size: int = 280,
                 world_height: float = 3.0, z_spread: float = 0.0,
                 world_width: float | None = None) -> np.ndarray:
    """一步到位：文字 → n 个世界坐标目标点。"""
    mask = render_text_mask(text, canvas=canvas, font_size=font_size)
    pts = mask_to_points(mask, world_height, z_spread, world_width)
    return sample_points(pts, n)
