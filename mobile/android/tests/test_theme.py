"""Token-level checks; these supplement, not replace, native render verification."""
from pathlib import Path
import re
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "app/src/main/java/local/werewolf/probe"


def luminance(value):
    rgb = [(int(value, 16) >> shift & 255) / 255 for shift in (16, 8, 0)]
    linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in rgb]
    return sum(c * weight for c, weight in zip(linear, (.2126, .7152, .0722)))


class ThemeContractTest(unittest.TestCase):
    def test_text_and_action_pairs_meet_contrast(self):
        tokens = dict(re.findall(r"val (\w+) = Color\(0xFF([A-F0-9]{6})\)", (SOURCE / "NightTheme.kt").read_text()))
        for theme in ("Light", "Dark"):
            for ink, ground in (
                ("Ink", "Ground"), ("Muted", "Ground"), ("Ink", "Surface"),
                ("Muted", "Surface"), ("Ink", "Raised"), ("Muted", "Raised"),
                ("Accent", "Ground"), ("Ink", "Selected"), ("Error", "Surface"),
                ("Accent", "Ground" if theme == "Dark" else "Surface"),
            ):
                with self.subTest(theme=theme, ink=ink, ground=ground):
                    a, b = sorted((luminance(tokens[theme + ink]), luminance(tokens[theme + ground])))
                    self.assertGreaterEqual((b + .05) / (a + .05), 4.5)

    def test_screen_uses_theme_roles_not_embedded_colors(self):
        screen = (SOURCE / "GameActivity.kt").read_text()
        self.assertNotIn("Color(0x", screen)
        self.assertIn("NightTheme { GameApp(model) }", screen)
        self.assertIn("isAppearanceLightNavigationBars = !dark", screen)

    def test_material_containers_are_explicit(self):
        theme = (SOURCE / "NightTheme.kt").read_text()
        for role in ("primaryContainer", "secondaryContainer", "tertiaryContainer",
                     "surfaceContainerLowest", "surfaceContainerHighest", "onBackground"):
            self.assertRegex(theme, rf"\b{role}\s*=")
        self.assertNotIn(".em", theme)
