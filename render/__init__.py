"""渲染层：ModernGL 点精灵渲染 + 轨道相机 + 程序化纹理。

设计约束：本包只依赖 moderngl + numpy（不依赖窗口库），
pytest 可用 standalone 上下文离屏渲染做像素级断言；
窗口/输入事件由 main.py（moderngl-window）接线。
"""
