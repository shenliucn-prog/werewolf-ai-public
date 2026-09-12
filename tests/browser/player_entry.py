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
        self.run_game(spectator=True)

    def test_player_choices_reload_and_settlement(self):
        self.run_game(spectator=False)

    def test_campaign_api_fixture_teaching_retry_and_settlement(self):
        self.run_game(spectator=False, campaign=True)

    def run_game(self, spectator, campaign=False):
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
                page = browser.new_page(viewport={"width": 1440 if campaign else 390, "height": 900 if campaign else 844})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("dialog", lambda dialog: dialog.accept())
                page.goto(url)
                self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
                artifacts = root / "output" / "playwright"
                artifacts.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(artifacts / ("entry-desktop.png" if campaign else "entry-mobile.png")), full_page=True)
                expect(page.locator("#continueGame")).to_be_disabled()
                page.locator("#entryInterface").select_option("web")
                if campaign:
                    expect(page.locator("#castNames input")).to_have_count(12)
                    with page.expect_response(lambda r: r.url.endswith("/api/start")) as unconfigured:
                        page.locator("#newGame").click()
                    self.assertEqual(unconfigured.value.status, 422)
                    self.assertIsNone(page.evaluate("localStorage.getItem('werewolf.game')"))
                    # Actual browser -> game backend -> synthetic HTTP provider.
                    fixture_url = page.request.get(url + "/test-fixture").json()["url"]
                    settings_toggle = page.locator("details.llm-settings:has(#driverMode) > summary")
                    page.locator("#driverMode").select_option("api")
                    expect(page.locator("#apiFields")).to_be_visible()
                    page.locator("#llmBaseUrl").fill(fixture_url)
                    page.locator("#llmModel").fill("synthetic-browser-fixture")
                    page.locator("#checkConnection").click()
                    expect(page.locator("#connectionFeedback")).to_contain_text("连接通过", timeout=15000)
                    self.assertIsNone(page.evaluate("localStorage.getItem('werewolf.game')"))
                    expect(page.locator("#characterChoice option")).to_have_count(32)
                    page.locator("#characterChoice").select_option("linque")
                    settings_toggle.click()
                    page.locator("#entryMode").select_option("campaign")
                    page.locator("#campaignGame").click()
                    expect(page.locator("#retryCampaignTeaching")).to_be_visible(timeout=15000)
                    page.locator("#retryCampaignTeaching").click()
                    expect(page.locator("#retryCampaignTeaching")).to_be_hidden(timeout=15000)
                else:
                    page.locator("#driverMode").select_option("offline")
                    page.locator("#offlineSetup").evaluate("el => el.open = true")
                    page.locator("#offlineSpectator").set_checked(spectator)
                    page.locator("#offlineGame").click()
                expect(page.locator("#actionPanel button").first).to_be_visible(timeout=15000)
                expect(page.locator("#table .seat")).to_have_count(12)
                page.screenshot(path=str(artifacts / ("roundtable-desktop.png" if campaign else "roundtable-mobile.png")), full_page=True)
                if campaign:
                    expect(page.locator("#playerBody")).to_contain_text("林雀")
                self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
                game_id = page.evaluate("JSON.parse(localStorage.getItem('werewolf.game')).game_id")
                self.assertTrue(game_id)
                page.reload()
                page.locator("#gameSetup").evaluate("el => el.open = true")
                page.locator("#entryInterface").select_option("web")
                page.locator("#entryMode").select_option("continue")
                page.locator("#continueGame").click()
                expect(page.locator("#actionPanel button").first).to_be_visible(timeout=15000)
                self.assertEqual(page.evaluate("JSON.parse(localStorage.getItem('werewolf.game')).game_id"), game_id)
                for _ in range(160):
                    if page.locator("#reviewMask").is_visible():
                        break
                    request_id = page.evaluate("pendingReq?.request_id")
                    kind = page.evaluate("pendingReq?.kind")
                    button = page.locator("#actionPanel button").first
                    if campaign:
                        if kind == "ready":
                            button = page.locator("#readyGame")
                        elif kind == "speech":
                            page.locator("#speechInput").fill("I am listening; this is a synthetic test.")
                            button = page.locator("#sendSpeech")
                        elif kind == "vote":
                            page.locator("#voteBtns button").first.click()
                            button = page.locator("#sendVote")
                        elif kind in ("night", "day_skill"):
                            button = page.locator("#sendNight")
                        elif kind == "model_retry":
                            self.fail("Fixture produced an invalid model decision")
                    with page.expect_response(lambda r: r.url.endswith("/api/action") and r.request.method == "POST") as response:
                        button.click()
                    self.assertTrue(response.value.json()["ok"])
                    page.wait_for_function("old => document.querySelector('#reviewMask').style.display !== 'none' || (pendingReq?.request_id !== old && document.querySelector('#actionPanel').style.display !== 'none')",
                                           arg=request_id, timeout=120000)
                else:
                    self.fail("Game did not settle within bounded player actions")
                expect(page.locator("#reviewMask")).to_be_visible(timeout=120000)
                self.assertTrue(page.locator("#reviewText").inner_text().strip())
                page.keyboard.press("Escape")
                expect(page.locator("#reviewMask")).to_be_hidden()
                page.locator("#openReview").click()
                expect(page.locator("#reviewMask")).to_be_visible()
                if campaign:
                    view = page.request.get(url + f"/api/rejoin?game_id={game_id}").json()["view"]
                    self.assertTrue(view["finished"])
                    self.assertTrue(view["counted"])
                    profile = page.request.get(url + "/test-profile").json()
                    self.assertEqual(profile["attempts"]["civilian"]["attempts"], 1)
                    self.assertEqual(profile["settled"], [game_id])
                    page.request.get(url + f"/api/rejoin?game_id={game_id}")
                    self.assertEqual(profile, page.request.get(url + "/test-profile").json())
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
