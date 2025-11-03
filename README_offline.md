# 离线打包与检测界面说明

本说明文档汇总离线一体化交付时需要同步给用户的要点，包括 CUDA 加速开关、高 DPI 适配、进度显示以及模型自检日志。请在生成便携包或单文件 EXE 时随应用一同分发。

## 新增功能摘要

- **CUDA 加速开关**：检测页新增 `CUDA 加速` 按钮，可在支持 CUDA 的设备上即时切换推理 providers 并重建 ONNX Runtime 会话。
- **高 DPI/缩放适配**：Windows 端自动启用 Per-Monitor V2 DPI 感知，并基于当前 DPI 设置 Tk 缩放，界面布局全面网格化，可在 100% / 125% / 150% 缩放下无需额外放大窗口即可完整展示。
- **进度条与剩余时间**：检测任务采用指数加权的实时进度与剩余时间估算，并在初始化阶段提供模拟动画，长时间模型加载时也会持续反馈。
- **日志与自检**：启动时在检测页日志中输出可用 providers、当前 providers 与 InsightFace 模型目录，切换 CUDA 时同步记录成功/失败信息。

## CUDA 加速按钮使用指南

1. 首次启动会根据 `~/.ctxphoto/config.json` 中的 `prefer_cuda` 记忆用户偏好，默认优先尝试启用 CUDA。
2. 当系统检测到 `onnxruntime` 且 `CUDAExecutionProvider` 可用时，按钮处于可点击状态：
   - **启用态**：绿色背景并带有 `✓`，表示当前会话将优先使用 CUDA，失败自动回退 CPU。
   - **关闭态**：恢复默认主题色，仅使用 `CPUExecutionProvider`。
   - **禁用态**：检测不到 CUDA 或驱动，按钮灰显不可用。
3. 切换时若重建会话失败，界面会提示错误原因，并强制退回 CPU 模式，同时将偏好写回配置文件。

> **提示**：如需在离线包中预置配置，可将生成好的 `config.json` 放置到用户主目录的 `.ctxphoto` 下。

## 高 DPI 适配说明

- 启动阶段调用 `SetProcessDpiAwareness(2)`/`SetProcessDPIAware`，确保在多显示器环境下获取真实 DPI。
- 根据设备 DPI 自动计算 `tk scaling`，配合网格布局实现控件自适应缩放。
- 主窗体默认大小约为 1180×760，最小尺寸限制为 960×640，用户可自由拉伸，侧边日志栏与预览区会同步扩展。

## 进度条与剩余时间

- 真实进度以照片数量为基准，后台线程定期回传完成数量与耗时，前台通过指数加权移动平均平滑速率。
- 未获取真实进度之前（例如模型加载阶段）会启动模拟动画：前 10 秒线性增长至 20%，此后保持缓慢推进，确保用户能看到明显反馈。
- 完成时强制刷新至 100%，并将剩余时间显示为 `00:00:00`；停止任务则显示 `--:--:--`。

## 日志与模型自检

- 检测页日志默认输出：
  1. `onnxruntime.get_available_providers()` 结果；
  2. 当前会话采用的 providers；
  3. InsightFace 模型目录及示例模型文件（若已安装）。
- 切换 CUDA 成功或失败均会追加日志，失败时附带回退提示。
- 若缺少 `onnxruntime` 或 InsightFace 模型，日志会给出安装提示，方便现场排查。

## 离线打包注意事项

- PyInstaller 打包需包含 `onnxruntime`、`mediapipe`、`insightface`（如需 GPU）、`numpy`、`Pillow` 等依赖。
- Windows 便携包建议保留 `venv` 内部的 CUDA/TensorRT 动态库，并在说明中提示显卡驱动版本要求。
- 如需脱机分发 InsightFace 模型，可将 `buffalo_l` 模型预解压到用户目录（`%APPDATA%/insightface/models` 或 `~/.insightface/models`），并在首次启动前写入对应路径。

## 故障排查建议

- **CUDA 按钮灰显**：确认 `onnxruntime-gpu` 已安装且正确加载 `CUDAExecutionProvider`，可在日志中查看 provider 列表。
- **模型初始化失败**：检查 InsightFace 模型目录是否包含 `.onnx` 文件，或是否缺失 `numpy`/`onnxruntime` 版本要求。
- **高 DPI 下界面拥挤**：确保 Windows 显示缩放比例未被系统覆盖，并检查是否禁用了应用的 DPI 感知（兼容性设置）。

将本说明与应用一同交付，可帮助最终用户快速理解 CUDA 加速、高 DPI 适配及进度展示的使用方式，并在离线环境下自助排查常见问题。
