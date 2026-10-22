# 镜织 FrameWeave 文档

<!-- 当前使用指南、技术资料与历史验收分别索引，避免把旧功能当作产品现状。 -->

镜织把主题、稿件和自有素材组织成视频。产品功能、安装与配置以当前指南为准；离线测试、真实 API 调用与历史验收分别记录。

## 当前使用指南

| 内容 | 中文 | English |
| --- | --- | --- |
| 产品与功能 | [文档首页](zh/index.md) | [Overview](en/index.md) |
| 安装与启动 | [安装指南](zh/getting-started/installation.md) | [Installation](en/getting-started/installation.md) |
| 第一个视频 | [快速入门](zh/getting-started/quick-start.md) | [Quick start](en/getting-started/quick-start.md) |
| 模型与密钥 | [配置指南](zh/getting-started/configuration.md) | [Configuration](en/getting-started/configuration.md) |
| 三步创作与作品管理 | [工作台指南](zh/user-guide/web-ui.md) | [Workspace guide](en/user-guide/web-ui.md) |
| 常见问题 | [FAQ](zh/faq.md) | [FAQ](en/faq.md) |
| 故障排查 | [排错指南](zh/troubleshooting.md) | [Troubleshooting](en/troubleshooting.md) |

界面内的简版帮助见 [中文 API 使用说明](frameweave-faq.zh.md) / [English API guide](frameweave-faq.en.md)。

## 专题说明

- [动态模型目录](dynamic-model-catalog.md)：加载、保存、连接失效与能力筛选。
- [Grok / Muse 接入](grok-muse-video.md)：接口协议、支持参数和能力边界。
- [统一启动说明](frameweave-unified-workspace.md)：端口、已有进程复用和退出行为。
- [功能优化方向](frameweave-roadmap.md)：围绕现有创作方式的改进。
- [模板开发](zh/user-guide/templates.md)：HTML 模板结构与内置预览。

## 开发记录与历史资料

带日期的实现说明、Issue 调研与验收文件记录当时状态，不等同于当前功能清单或所有模型的真实生成验收。例如：[API 模式记录](api-only-workspace.md)、[三步布局验收](creation-flow-validation-2026-10-21.md)、[动态目录验证](dynamic-model-catalog.md)、[素材长视频记录](custom-media-long-video-2026-10-21.md)。

[早期实验验收](frameweave-validation.md)、[实验接口契约](frameweave-contract.md)、[旧版界面记录](studio-ui.md)保留用于追溯。原工作流、声音克隆、SDK、架构及上游视频示例归入文档站的“历史兼容参考”，不表示当前 Web 工作台提供这些入口。

## 参考与感谢

镜织参考并基于 [Pixelle-Video](https://github.com/ATH-MaaS/Pixelle-Video) 开发，感谢上游贡献。许可证与第三方声明见 [LICENSE](../LICENSE) 和 [NOTICE](../NOTICE)。
