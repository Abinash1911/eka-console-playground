"""Step 1 of the ribbon chain check: what the console would save, as the agent-config response.

Runs the console's own save logic (dev-console agents/services/ribbon.py) on a
simulated form post, then wraps the agent theme in the same envelope matrix's
agent-config route returns ({"success": true, "data": {...}}). The matrix model
itself is not run here (it needs the echo SDK); the envelope is copied from
med_assist/router/agent_config.py.
"""
import importlib.util
import json
import os
import sys

DC = os.environ.get("DC", "/home/user/dev-console")
spec = importlib.util.spec_from_file_location("ribbon", f"{DC}/agents/services/ribbon.py")
ribbon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ribbon)

post = {
    "ribbon_text": "Send 2 messages, get ₹20",
    "ribbon_dismissable": "1",
    "ribbon_icon": "custom",
    "ribbon_background": "#1e3a8a",
    "ribbon_text_color": "#ffd54a",
}
upload = type("Upload", (), {"name": "offer.png", "content_type": "image/png", "size": 2048})()
saved_to = []


def save_file(f):  # stands in for _save_theme_image (public media storage)
    saved_to.append(f.name)
    return "https://cdn.eka.care/1/agents/theme/7/ribbon_icon/" + f.name


icon_img = ribbon.resolve_icon_img(post, {"ribbon_icon_file": upload}, None, save_file)
theme = {"accent": "#215fff", "ribbon": ribbon.build_ribbon(post, icon_img=icon_img)}
assert saved_to == ["offer.png"], saved_to
json.dump({"success": True, "data": {"name": "Chain Test Agent", "theme": theme, "allowed": ["text"], "connectivity": "socket"}}, sys.stdout)
