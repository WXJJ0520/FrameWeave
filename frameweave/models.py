"""FrameWeave API 输入模型；限制字段，避免密钥和任意路径进入项目文件。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Scene(InputModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    title: str = Field(default="新镜头", max_length=200)
    narration: str = Field(default="", max_length=10000)
    prompt: str = Field(default="", max_length=10000)
    duration: float = Field(default=4, ge=1, le=60)
    media_asset_id: str | None = None
    audio_asset_id: str | None = None
    presenter_asset_id: str | None = None
    layout: Literal["full", "pip"] = "full"


class CreateProject(InputModel):
    title: str = Field(default="未命名项目", min_length=1, max_length=200)
    recipe_id: Literal["blank", "tutorial", "knight-cat", "comparison"] = "blank"


class UpdateProject(InputModel):
    revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    width: int | None = Field(default=None, ge=240, le=3840)
    height: int | None = Field(default=None, ge=240, le=3840)
    fps: int | None = Field(default=None, ge=12, le=60)
    language: Literal["zh-CN", "en"] | None = None
    scenes: list[Scene] | None = Field(default=None, max_length=100)

    @field_validator("width", "height")
    @classmethod
    def even_dimensions(cls, value):
        # H.264/yuv420p 要求偶数尺寸，提前反馈避免到合成阶段才失败。
        if value is not None and value % 2:
            raise ValueError("视频宽高必须是偶数")
        return value


class RestoreProject(InputModel):
    revision: int = Field(ge=1)
    expected_revision: int = Field(ge=1)
    scene_id: str | None = None


class JobParams(InputModel):
    workflow: str | None = Field(default=None, max_length=300)
    media_type: Literal["image", "video"] | None = None
    duration: float | None = Field(default=None, ge=1, le=60)
    voice: str | None = Field(default=None, max_length=100)
    use_reference: bool = False

    @field_validator("workflow")
    @classmethod
    def api_workflow_only(cls, value):
        if value is not None and not value.startswith("api/"):
            raise ValueError("镜织工作台仅接受 API 模型工作流标识")
        return value


class CreateJob(InputModel):
    operation: Literal["render", "generate_media", "generate_audio"]
    scene_id: str | None = None
    params: JobParams = Field(default_factory=JobParams)

    @model_validator(mode="after")
    def require_scene_and_model(self):
        if self.operation != "render" and not self.scene_id:
            raise ValueError("单镜生成必须指定 scene_id")
        if self.operation == "generate_media" and not self.params.workflow:
            raise ValueError("生成画面必须选择 workflow 模型")
        return self
