# 工作流定制

<!-- Preserve historical content and attribution; current usage is documented separately. -->

> **历史兼容参考**：下文保留原项目的操作、接口或示例记录，不代表镜织当前 Web 功能或实测结果。当前用法以[镜织文档首页](../index.md)、[配置指南](../getting-started/configuration.md)为准。

如何自定义 ComfyUI 工作流以实现特定功能。

---

## 工作流简介

Pixelle-Video 基于 ComfyUI 架构，支持自定义工作流。

---

## 工作流类型

### TTS 工作流

位于 `workflows/selfhost/` 或 `workflows/runninghub/`

用于文本转语音（Text-to-Speech），支持多种 TTS 引擎：
- Edge-TTS
- Index-TTS（支持声音克隆）
- 其他 ComfyUI 兼容的 TTS 节点

### 图像生成工作流

位于 `workflows/selfhost/` 或 `workflows/runninghub/`

用于生成静态图像作为视频背景：
- FLUX 系列模型
- Stable Diffusion 系列模型
- 其他图像生成模型

### 视频生成工作流

位于 `workflows/selfhost/` 或 `workflows/runninghub/`

**新功能**：支持 AI 视频生成，创建动态视频内容。

**预置工作流**：
- `runninghub/video_wan2.1_fusionx.json`: 云端工作流（推荐）
  - 基于 WAN 2.1 模型
  - 无需本地环境，通过 RunningHub API 调用
  - 支持文本到视频（Text-to-Video）
  
- `selfhost/video_wan2.1_fusionx.json`: 本地工作流
  - 需要本地 ComfyUI 环境
  - 需要安装相应的视频生成节点
  - 适合有本地 GPU 的用户

**使用场景**：
- 配合 `video_*.html` 模板使用
- 自动根据文案生成动态视频背景
- 增强视频的视觉表现力和观看体验

---

## 自定义工作流

1. 在 ComfyUI 中设计你的工作流
2. 导出为 JSON 文件
3. 放置到 `workflows/` 目录
4. 在 Web 界面中选择使用

---

## 更多信息

即将推出更详细的工作流定制指南。

