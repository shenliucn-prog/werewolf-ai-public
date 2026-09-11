"""Real HTTP server with disposable persistence; never load local credentials."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from werewolf_web import config

config._env.clear()
for name in list(os.environ):
    if name.startswith(("LLM_", "WEREWOLF_AGENT_", "OPENAI_")):
        os.environ.pop(name)
config.Config.LLM_API_KEY = ""
config.Config.LLM_ENABLED = False

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="werewolf-browser-") as directory:
        config.DATA_DIR = directory
        config.REVIEW_DIR = os.path.join(directory, "reviews")
        config.HOST_STYLE_PATH = os.path.join(directory, "host_style.json")
        import uvicorn
        from werewolf_web.run import app
        from tests.browser_model import start_fixture
        fixture = start_fixture()
        @app.get("/test-fixture")
        def fixture_address():
            return {"url": f"http://127.0.0.1:{fixture.server_port}/v1"}
        @app.get("/test-profile")
        def profile_summary():
            from werewolf_web.campaign_flow import load_profile
            profile = load_profile("default")
            return {key: profile[key] for key in ("attempts", "settled", "unlocked")}
        # Product mounts static files at '/'; fixture-only routes must precede it.
        fixture_routes = app.router.routes[-2:]
        del app.router.routes[-2:]
        app.router.routes[:0] = fixture_routes
        uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
        fixture.shutdown()
