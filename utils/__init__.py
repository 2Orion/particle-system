"""工具包：文字采样与视频录制（plan §3 utils/）。"""
from .recorder import Recorder
from .sampling import (mask_to_points, render_text_mask, sample_points,
                       text_targets)

__all__ = ["Recorder", "render_text_mask", "mask_to_points",
           "sample_points", "text_targets"]
