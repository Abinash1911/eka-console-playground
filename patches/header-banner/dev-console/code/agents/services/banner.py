"""Widget banner (`theme.banner`): one line of text under the widget header.

Colours come from the accent colour, so the text is all there is to save.
Pure Python, so it is tested without a database.
"""

from typing import Optional

BANNER_MAX_LENGTH = 200


def clean_banner(raw) -> Optional[str]:
    """The text to store under `theme["banner"]`, or None when there is none.

    One line: runs of whitespace (including line breaks) become one space.
    Cut at BANNER_MAX_LENGTH characters, spaces included.
    """
    text = " ".join(str(raw or "").split())[:BANNER_MAX_LENGTH].strip()
    return text or None
