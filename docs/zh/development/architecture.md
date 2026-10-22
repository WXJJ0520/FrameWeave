# 架构设计

<!-- Preserve historical content and attribution; current usage is documented separately. -->

> **历史兼容参考**：下文保留原项目的操作、接口或示例记录，不代表镜织当前 Web 功能或实测结果。当前用法以[镜织文档首页](../index.md)、[配置指南](../getting-started/configuration.md)为准。

Pixelle-Video 的技术架构概览。

---

## 核心架构

Pixelle-Video 采用分层架构设计：

- **Web 层**: Streamlit Web 界面
- **服务层**: 核心业务逻辑
- **ComfyUI 层**: 图像和TTS生成

---

## 主要组件

### PixelleVideoCore

核心服务类，协调各个子服务。

### LLM Service

负责调用大语言模型生成文案。

### Image Service

负责调用 ComfyUI 生成图像。

### TTS Service

负责调用 ComfyUI 生成语音。

### Video Generator

负责合成最终视频。

---

## 技术栈

- **后端**: Python 3.10+, AsyncIO
- **Web**: Streamlit
- **AI**: OpenAI API, ComfyUI
- **配置**: YAML
- **工具**: uv (包管理)

---

## 更多信息

详细的架构文档即将推出。

