"""Guard the GameSession extraction boundary.

`werewolf_web/session.py` must stay transport-neutral: importing it directly
must not pull in FastAPI. Only `run.py` (the web adapter) may touch the web
framework. This test runs in a fresh subprocess so FastAPI already being loaded
by other test modules cannot mask a regression.
"""
import os
import subprocess
import sys
import unittest


class SessionIsolationTest(unittest.TestCase):
    def test_importing_session_does_not_load_fastapi(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        code = (
            "import sys\n"
            "import werewolf_web.session\n"
            "assert 'fastapi' not in sys.modules, 'werewolf_web.session imported fastapi'\n"
            "assert 'starlette' not in sys.modules, 'werewolf_web.session imported starlette'\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
