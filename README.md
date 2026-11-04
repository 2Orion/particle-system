# 项目说明

本项目为2026秋冬学期jxg老师的计算机动画课程的课程作业，选择粒子系统作为主题。

# 当前进度

- 第一轮（引擎核心）：`core/` 六模块（粒子池/积分器/力场/发射器/碰撞/系统调度）
- 第二轮（渲染 + 首场景）：`render/` 四模块、`scenes/fountain.py` 喷泉、`main.py` 入口
- 第三轮（三新场景）：烟花/火焰/雪三场景，数字键切换
- 第四轮（文字粒子 + 面板 + 录制）：文字→点云采样与软约束 morph、ImGui 参数面板、MP4 录制
- 第五轮（报告 + 修复）：`report.typ` 课程报告（17 页，数据全部由
  `tools/report_metrics.py` 离线复算）；顺带修复 Verlet/Leap-Frog 首步
  ½ah² 精度缺陷与面板滑条同帧拖动失效 —— 238 个 pytest 测试全部通过

详见 [CHANGELOG.md](./CHANGELOG.md) 与 [plan.md](./plan.md)；
按文件结构逐模块讲解的代码导读见 [textbook.md](./textbook.md)。

# 运行

```bash
pip install -r requirements.txt
python main.py
```

| 操作 | 按键 |
|---|---|
| 旋转相机 | 左键拖拽 |
| 平移 / 缩放 | 右键拖拽 / 滚轮 |
| 切换场景 | `1` 喷泉 / `2` 雪 / `3` 火焰 / `4` 烟花 / `5` 文字 |
| 参数面板显隐 | `G` |
| 录制 MP4 开 / 关 | `R` |
| 重置当前场景 | `T` |
| 暂停 / 继续 | `Space` |
| 截图到 `output/` | `F` |
| 退出 | `Esc` |

面板里的改动（积分器、固定步长、发射率、各力场参数、约束刚度、粒子尺寸、
文字内容）**即时生效**，不需要重启。文字场景下移动鼠标可直接扰动粒子；
面板字号会随窗口放大（全屏下按窗口比例自动放大最多 2.5 倍）。

# 场景

| 场景 | 混合 | 纹理 | 要点 |
|---|---|---|---|
| 喷泉 Fountain | additive | 高斯光斑 | 主喷+双侧水拱，地面弹性碰撞 |
| 雪 Snow | alpha | 软圆盘 | 大范围体积源，弱重力+阻力+侧风，落地即消 |
| 火焰 Fire | additive | 软圆盘 | 浮力（∝剩余生命）+ 伪湍流，黄→橙→红→灰 |
| 烟花 Fireworks | additive | 高斯光斑 | 解析弹道火箭 + 顶点球面爆发 + 上升光尾 |
| 文字 Text | additive | 高斯光斑 | 字形采样点云 + 软约束汇聚，可换字 morph、鼠标扰动 |

# 依赖说明

`numpy` / `moderngl` / `moderngl-window` / `pillow` 是必需项；`imgui-bundle`
与 `imageio-ffmpeg` 为可选增强，缺失时自动降级（无面板/无法录制），不会崩溃。

# 运行测试

```bash
pip install -r requirements-dev.txt
python -m pytest          # 238 个用例，20–50 秒
```

需要 OpenGL 上下文的渲染断言会在无显卡环境自动跳过。

# 参考资料
1. [粒子系统实现与原理](https://zhuanlan.zhihu.com/p/630778848)
2. [计算机动画原理与技术（三）粒子系统](https://zhuanlan.zhihu.com/p/483273489)
3. [jxg老师PPT](./docs/Lecture6(5).pdf)
4. [课程作业要求](./docs/project_needs.pdf)