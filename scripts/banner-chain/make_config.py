"""Step 1 of the banner chain check: what the console would save, as the agent-config response.

Runs the console's own save logic (dev-console agents/services/banner.py) on a
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
spec = importlib.util.spec_from_file_location("banner", f"{DC}/agents/services/banner.py")
banner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(banner)

theme = {"accent": "#215fff", "banner": banner.clean_banner("  Chat and earn coins \n")}
json.dump({"success": True, "data": {"name": "Chain Test Agent", "theme": theme, "allowed": ["text"], "connectivity": "socket"}}, sys.stdout)
