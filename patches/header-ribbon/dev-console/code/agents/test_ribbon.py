"""Widget header ribbon settings (`agents.services.ribbon`). DB-free."""

from django.test import SimpleTestCase

from agents.services.ribbon import RIBBON_TEXT_MAX_LENGTH, build_ribbon


class BuildRibbonTests(SimpleTestCase):
    def test_no_text_means_no_ribbon(self):
        self.assertIsNone(build_ribbon({}))
        self.assertIsNone(build_ribbon({"ribbon_text": "   "}))
        # Settings without text are dropped, not stored half-filled.
        self.assertIsNone(build_ribbon({"ribbon_background": "#112233", "ribbon_icon": "gift"}))

    def test_text_only_is_fixed_with_no_extras(self):
        self.assertEqual(
            build_ribbon({"ribbon_text": "  Send 2 messages, get ₹20 "}),
            {"text": "Send 2 messages, get ₹20", "dismissable": False},
        )

    def test_everything_set(self):
        post = {
            "ribbon_text": "By chatting, you agree to our privacy policy.",
            "ribbon_dismissable": "1",
            "ribbon_icon": "shield",
            "ribbon_background": "#fef3c7",
            "ribbon_text_color": "#92400e",
        }
        self.assertEqual(
            build_ribbon(post),
            {
                "text": "By chatting, you agree to our privacy policy.",
                "dismissable": True,
                "icon": "shield",
                "background": "#fef3c7",
                "text_color": "#92400e",
            },
        )

    def test_dismissable_only_when_checked(self):
        self.assertFalse(build_ribbon({"ribbon_text": "Hi", "ribbon_dismissable": ""})["dismissable"])
        self.assertFalse(build_ribbon({"ribbon_text": "Hi", "ribbon_dismissable": "0"})["dismissable"])
        self.assertTrue(build_ribbon({"ribbon_text": "Hi", "ribbon_dismissable": "1"})["dismissable"])

    def test_unknown_icon_is_dropped(self):
        for icon in ("", "none", "rocket", "<script>"):
            self.assertNotIn("icon", build_ribbon({"ribbon_text": "Hi", "ribbon_icon": icon}))
        for icon in ("gift", "info", "megaphone", "sparkles", "shield"):
            self.assertEqual(build_ribbon({"ribbon_text": "Hi", "ribbon_icon": icon})["icon"], icon)

    def test_only_hex_colours_are_kept(self):
        for good in ("#fff", "#FFFFFF", "#1e3a8a"):
            self.assertEqual(build_ribbon({"ribbon_text": "Hi", "ribbon_background": good})["background"], good)
        for bad in ("", "red", "#12", "#12345", "#1234567", "rgb(0,0,0)", "red; display:none", "url(x)"):
            ribbon = build_ribbon({"ribbon_text": "Hi", "ribbon_background": bad, "ribbon_text_color": bad})
            self.assertNotIn("background", ribbon)
            self.assertNotIn("text_color", ribbon)

    def test_text_is_capped(self):
        ribbon = build_ribbon({"ribbon_text": "x" * (RIBBON_TEXT_MAX_LENGTH + 50)})
        self.assertEqual(len(ribbon["text"]), RIBBON_TEXT_MAX_LENGTH)
