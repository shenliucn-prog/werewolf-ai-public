"""Real Chromium + HTTP + SSE; synthetic offline game, no paid models."""
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path
from urllib.request import urlopen
from playwright.sync_api import sync_playwright, expect


class BrowserEntryTest(unittest.TestCase):
    def test_ready_reload_and_spectator_settlement(self):
        root = Path(__file__).resolve().parents[2]
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        process = subprocess.Popen([sys.executable, str(root / "tests/browser_server.py"), str(port)], cwd=root)
        try:
            url = f"http://127.0.0.1:{port}"
            for _ in range(100):
                try:
                    with urlopen(url, timeout=1):
                        break
                except OSError:
                    if process.poll() is not None:
                        self.fail("Test HTTP server exited")
                    time.sleep(.1)
            else:
                self.fail("Test HTTP server did not start")
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("dialog", lambda dialog: dialog.accept())
                page.goto(url)
                page.locator("#offlineSetup").evaluate("el => el.open = true")
                page.locator("#offlineSpectator").check()
                page.locator("#offlineGame").click()
                expect(page.locator("#actionPanel button").first).to_be_visible(timeout=15000)
                game_id = page.evaluate("JSON.parse(localStorage.getItem('werewolf.game')).game_id")
                self.assertTrue(game_id)
                page.reload()
                page.locator("#continueGame").click()
                expect(page.locator("#actionPanel button").first).to_be_visible(timeout=15000)
                self.assertEqual(page.evaluate("JSON.parse(localStorage.getItem('werewolf.game')).game_id"), game_id)
                page.locator("#actionPanel button").first.click()
                expect(page.locator("#reviewMask")).to_be_visible(timeout=120000)
                self.assertTrue(page.locator("#reviewText").inner_text().strip())
                self.assertEqual(errors, [])
                browser.close()
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
