"""Widget header ribbon (`theme.ribbon`): read the Appearance form into the theme JSON.

Pure Python, so it is tested without a database. The widget reads the saved
shape through the agent-config API: text, dismissable, icon, background,
text_color (hex).
"""

import re
from typing import Optional

RIBBON_ICONS = ("gift", "info", "megaphone", "sparkles", "shield")
RIBBON_TEXT_MAX_LENGTH = 200
_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def build_ribbon(post) -> Optional[dict]:
    """The ribbon dict to store under `theme["ribbon"]`, or None when there is no text."""
    text = (post.get("ribbon_text", "") or "").strip()[:RIBBON_TEXT_MAX_LENGTH]
    if not text:
        return None

    ribbon = {
        "text": text,
        "dismissable": post.get("ribbon_dismissable", "") == "1",
    }
    icon = post.get("ribbon_icon", "")
    if icon in RIBBON_ICONS:
        ribbon["icon"] = icon
    background = (post.get("ribbon_background", "") or "").strip()
    if _HEX_COLOR.match(background):
        ribbon["background"] = background
    text_color = (post.get("ribbon_text_color", "") or "").strip()
    if _HEX_COLOR.match(text_color):
        ribbon["text_color"] = text_color
    return ribbon
