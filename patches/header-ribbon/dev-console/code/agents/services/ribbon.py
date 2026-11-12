"""Widget header ribbon (`theme.ribbon`): read the Appearance form into the theme JSON.

Pure Python, so it is tested without a database. The widget reads the saved
shape through the agent-config API: text, dismissable, icon or icon_img (an
uploaded image), background, text_color (hex).
"""

import re
from typing import Callable, Optional

RIBBON_ICONS = ("gift", "info", "megaphone", "sparkles", "shield")
RIBBON_TEXT_MAX_LENGTH = 200
RIBBON_ICON_MAX_BYTES = 1024 * 1024  # an uploaded icon is drawn at 16px; 1 MB is plenty
_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def resolve_icon_img(post, files, saved: Optional[str], save_file: Callable) -> Optional[str]:
    """The URL for `theme["ribbon"]["icon_img"]`, or None.

    Only when "Upload your own" is picked in the icon select. A new upload wins
    over a pasted URL, which wins over the icon already saved; "clear" drops it.
    The widget only draws https images, so a pasted http URL is not accepted.
    `save_file(upload)` stores the file and returns its public URL.
    """
    if post.get("ribbon_icon") != "custom" or post.get("clear_ribbon_icon_img") == "1":
        return None
    upload = files.get("ribbon_icon_file")
    if upload is not None and str(getattr(upload, "content_type", "")).startswith("image/") and (
        getattr(upload, "size", 0) or 0
    ) <= RIBBON_ICON_MAX_BYTES:
        return save_file(upload)
    url = (post.get("ribbon_icon_url", "") or "").strip()
    if url.lower().startswith("https://"):
        return url
    return saved or None


def build_ribbon(post, icon_img: Optional[str] = None) -> Optional[dict]:
    """The ribbon dict to store under `theme["ribbon"]`, or None when there is no text.

    `icon_img` is the uploaded icon's URL from `resolve_icon_img`; it replaces the preset icon.
    """
    text = (post.get("ribbon_text", "") or "").strip()[:RIBBON_TEXT_MAX_LENGTH]
    if not text:
        return None

    ribbon = {
        "text": text,
        "dismissable": post.get("ribbon_dismissable", "") == "1",
    }
    icon = post.get("ribbon_icon", "")
    if icon_img:
        ribbon["icon_img"] = icon_img
    elif icon in RIBBON_ICONS:
        ribbon["icon"] = icon
    background = (post.get("ribbon_background", "") or "").strip()
    if _HEX_COLOR.match(background):
        ribbon["background"] = background
    text_color = (post.get("ribbon_text_color", "") or "").strip()
    if _HEX_COLOR.match(text_color):
        ribbon["text_color"] = text_color
    return ribbon
