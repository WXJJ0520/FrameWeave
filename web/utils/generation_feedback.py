"""数字人口播的阶段反馈：只报告实际执行位置，不根据异常文案猜测根因。"""

from dataclasses import dataclass


class MissingGeneratedVideoError(RuntimeError):
    """服务已经返回结果，但没有可供后续下载的视频地址。"""


@dataclass
class GenerationProgress:
    """由调用点显式更新阶段；嵌套异步函数共享状态，不改变任何生成调用。"""

    stage: str = "preparation"


@dataclass(frozen=True)
class GenerationFailure:
    """可以安全展示与记录的诊断，不保存原始异常、URL 或请求参数。"""

    stage: str
    message: str
    hint: str
    exception_type: str
    http_status: int | None

    @property
    def diagnostic(self) -> str:
        """技术详情只保留固定阶段、异常类型与合法 HTTP 状态码。"""
        fields = [f"stage={self.stage}", f"error_type={self.exception_type}"]
        if self.http_status is not None:
            fields.append(f"http_status={self.http_status}")
        return "\n".join(fields)


# 建议描述检查位置，而不是将未知异常归因于某个 Key、模型或平台。
_STAGES = {
    "preparation": (
        "流程准备",
        "workflow preparation",
        "请检查视频 API 服务地址、密钥、模型能力和人物素材是否可用。",
        "Check the video API URL, key, model capabilities and character inputs.",
    ),
    "pre_image": (
        "前置图片生成",
        "pre-image generation",
        "请检查图片 API 模型，以及人物和商品图片的输入要求。",
        "Check the image API model and its character/product image requirements.",
    ),
    "script": (
        "口播文案生成",
        "script generation",
        "请检查系统配置中的文案模型和连接设置；也可以填写自己的口播文案。",
        "Check the text model and connection settings, or provide your own narration script.",
    ),
    "speech": (
        "配音合成",
        "speech synthesis",
        "请先在配音设置中试听。Edge TTS 是在线语音接口，请检查网络和服务状态。",
        "Try the voice preview first. Edge TTS is an online speech API; check network and service availability.",
    ),
    "video": (
        "口播视频生成",
        "talking-video generation",
        "请检查所选口播 API 模型的权限和输入要求；普通图生视频 API 不一定支持参考声音。",
        "Check access and input requirements for the talking-video API. Ordinary image-to-video APIs may not support reference voice.",
    ),
    "download": (
        "视频结果获取与保存",
        "video retrieval and saving",
        "服务已返回视频地址，请检查结果链接可访问性，以及输出目录权限和磁盘空间；无需先重新生成。",
        "A video URL was returned. Check result access, output-folder permissions and disk space before generating again.",
    ),
    "history": (
        "作品记录保存",
        "history saving",
        "视频已生成，请先检查本次输出目录，再检查作品记录存储，避免重复生成。",
        "The video was generated. Check the output folder and history storage before generating again.",
    ),
    "result": (
        "结果展示",
        "result display",
        "视频已生成，请检查本次输出文件是否可读取；展示失败不代表需要重新生成。",
        "The video was generated. Check that the output file is readable; a display failure does not require regeneration.",
    ),
}


def build_generation_failure(
    stage: str, error: Exception, language: str = "zh_CN"
) -> GenerationFailure:
    """根据已知阶段生成提示；不解析原始错误，防止第三方令牌 URL 进入界面和日志。"""
    known = stage in _STAGES
    safe_stage = stage if known else "unknown"
    zh = language == "zh_CN"
    if known:
        cn_label, en_label, cn_hint, en_hint = _STAGES[stage]
        label, hint = (cn_label, cn_hint) if zh else (en_label, en_hint)
        message = (
            f"数字人口播在「{label}」阶段未完成。"
            if zh
            else f"Digital human creation did not complete during {label}."
        )
        if stage in {"history", "result"}:
            message = (
                f"视频已生成，但「{label}」未完成。"
                if zh
                else f"The video was generated, but {label} did not complete."
            )
    else:
        message = (
            "数字人口播流程未完成，当前信息不足以确定失败阶段。"
            if zh
            else "Digital human creation did not complete; the failing stage is unknown."
        )
        hint = (
            "请核对当前流程配置和输入；此提示不能确定是哪一项服务发生故障。"
            if zh
            else "Check the current configuration and inputs; this message does not identify a failing service."
        )
    if stage == "video" and isinstance(error, MissingGeneratedVideoError):
        message = (
            "口播视频服务已返回结果，但其中没有可用的视频地址。"
            if zh
            else "The talking-video service returned a result without a usable video URL."
        )

    # 只取 SDK 的结构化状态码；不读取可能含凭据的 message、request、response body。
    status = getattr(error, "status_code", None) or getattr(error, "status", None)
    if status is None:
        status = getattr(getattr(error, "response", None), "status_code", None)
    if type(status) is not int or not 100 <= status <= 599:
        status = None
    exception_type = type(error).__name__
    if not exception_type.isidentifier() or len(exception_type) > 80:
        exception_type = "Exception"
    return GenerationFailure(safe_stage, message, hint, exception_type, status)
