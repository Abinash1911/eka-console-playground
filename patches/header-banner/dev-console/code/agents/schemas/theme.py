from typing import Literal, Optional

from pydantic import BaseModel


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
    banner: Optional[str] = None  # one line under the widget header; colours come from the accent
