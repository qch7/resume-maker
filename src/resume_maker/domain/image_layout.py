"""定义图片模板的空间识别数据结构"""

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from resume_maker.domain.models import Model

Coordinate = Annotated[float, Field(ge=0, le=1)]
Color = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]


class ImageRegion(Model):
    """页面内的比例矩形，独立于分辨率和图片不可靠的 DPI 元数据"""

    box: list[Coordinate] = Field(min_length=4, max_length=4)

    @field_validator("box")
    @classmethod
    def valid_box(cls, box):
        """拒绝空框和反向框以便重试识别"""
        if box[0] >= box[2] or box[1] >= box[3]:
            raise ValueError("文字或素材必须有正面积的位置框。")
        return box


class ImageText(ImageRegion):
    """单个可见文字行，保留同行不同字段的独立位置和文字样式"""

    text: str = Field(min_length=1, max_length=4000)
    font_name: str = Field(default="等线", min_length=1, max_length=100)
    bold: bool = False
    color: Color = "#222222"

    @field_validator("text")
    @classmethod
    def visible_text(cls, text):
        """只有可见单行文字才能得到可靠字宽，空白和换行须另行分行"""
        if not text.strip() or "\n" in text or "\r" in text:
            raise ValueError("每个文字框必须是非空的单行文字。")
        return text


class ImageAsset(ImageRegion):
    """无文字裁图和重新绘制的底块分开，底块不能把旧栏目文字烘焙进图片"""

    kind: Literal["photo", "icon", "shape", "background", "line"]
    color: Color = "#222222"
    polygon: list[list[Coordinate]] = Field(default_factory=list, max_length=24)

    @model_validator(mode="after")
    def valid_polygon(self):
        """多边形采用页面比例坐标，必须完整落在声明区域内"""
        if self.polygon and (
            len(self.polygon) < 3
            or self.kind not in {"shape", "background"}
            or any(
                len(point) != 2
                or not self.box[0] <= point[0] <= self.box[2]
                or not self.box[1] <= point[1] <= self.box[3]
                for point in self.polygon
            )
        ):
            raise ValueError("底块多边形必须有至少三个点，并完全位于素材框内。")
        return self


class ImagePage(Model):
    """可编辑文字、局部素材和显式不确定项，禁止把整页作为恢复成品"""

    texts: list[ImageText] = Field(min_length=1, max_length=1500)
    assets: list[ImageAsset] = Field(default_factory=list, max_length=300)
    notes: list[str] = Field(default_factory=list, max_length=30)
