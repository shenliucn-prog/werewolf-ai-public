"""The offline engine can run without installing any network/model SDK."""
import subprocess
import sys
import unittest
from pathlib import Path


class OfflineDependencyTest(unittest.TestCase):
    def run_isolated(self, source, *arguments):
        result = subprocess.run(
            [sys.executable, "-S", "-c", source, *arguments],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_classic_game_and_disk_restore_without_site_packages_or_network(self):
        source = '''
import asyncio
import json
import os
import sys
import tempfile
from werewolf_web.offline_web import WebOfflineSession
from werewolf_web.offline_game import action_choices
from werewolf_web.checkpoint import load_checkpoint

def no_external_io(event, args):
    if event in ("socket.connect", "socket.getaddrinfo", "subprocess.Popen"):
        raise AssertionError("Offline gameplay attempted external IO: " + event)
sys.addaudithook(no_external_io)

async def fast_pause(seconds=0):
    await asyncio.sleep(0)

async def finish(session):
    session._pace = fast_pause
    async for event in session.events():
        if event["type"] == "error":
            raise AssertionError(event)
        if event["type"] == "request" and session.pending:
            if event["request_id"] != session._human_request().request_id:
                continue
            choices = action_choices(session, event["kind"], event["data"])
            selected = session.auto_choice(event["kind"], event["data"], choices)
            assert session.submit_choice(selected["id"], event["request_id"])
    assert session.finished and not session.faulted
    assert session.engine.winner in ("god", "wolf", "draw")
    assert session.planner is None and not session.llm.runtime.enabled
    assert session.campaign_counted is False

async def main(directory):
    for locale in (sys.argv[1],):
        path = os.path.join(directory, locale + ".json")
        session = WebOfflineSession(seed=7, locale=locale,
            session_id="no-sdk-" + locale, checkpoint_path=path)
        session.memory_dir = directory
        await finish(session)
        restored = WebOfflineSession(seed=99, locale=locale,
            session_id=session.session_id, checkpoint_path=path)
        restored.memory_dir = directory
        restored.restore(load_checkpoint(path))
        # JSON object keys (for example vote tally seat numbers) are strings on disk.
        assert json.loads(json.dumps(restored.snapshot())) == json.loads(json.dumps(session.snapshot()))
        assert restored.engine.public_state() == session.engine.public_state()
        assert not any(n in sys.modules for n in ("httpx", "openai", "fastapi", "uvicorn"))

with tempfile.TemporaryDirectory() as directory:
    asyncio.run(main(directory))
'''
        # Each complete game gets the existing bounded process timeout. Running
        # two languages in one process made the combined disk work exceed it on
        # CI. Keep all gameplay, network isolation and restore assertions intact.
        for locale in ("en", "zh-CN"):
            with self.subTest(locale=locale):
                self.run_isolated(source, locale)

    def test_api_without_http_dependency_fails_explicitly(self):
        self.run_isolated('''
from werewolf_web.ai.decision_runtime import APIPlayerRuntime, ModelTurnError
from werewolf_web.ai.llm import LLMRuntimeConfig
runtime = APIPlayerRuntime(LLMRuntimeConfig.from_request({
    "enabled": True, "model": "test", "base_url": "http://localhost:1/v1"}))
try:
    runtime.complete({}, {})
except ModelTurnError as error:
    assert "dependency is missing" in str(error), str(error)
else:
    raise AssertionError("Missing API dependency was silently accepted")
''')
