from typing import Literal, Optional

from pydantic import BaseModel


class RibbonConfig(BaseModel):
    """Header ribbon shown under the widget header (theme.ribbon)."""

    text: str
    dismissable: bool = False
    icon: Optional[Literal["gift", "info", "megaphone", "sparkles", "shield"]] = None
    background: Optional[str] = None  # hex; absent -> the accent colour
    text_color: Optional[str] = None  # hex; absent -> black or white, whichever reads better
    id: Optional[str] = None  # change to show it again to people who closed an older one


class ThemeConfig(BaseModel):
    """UI theme configuration stored in agent_configs.theme JSONB."""

    background_img: Optional[str] = None
    accent: Optional[str] = None
    mode: Optional[Literal["light", "dark"]] = None
    title_img: Optional[str] = None
    icon_img: Optional[str] = None
    assistant_icon: Optional[str] = None
    header_tinted: Optional[bool] = None
    nudge_color: Optional[str] = None
    ribbon: Optional[RibbonConfig] = None
