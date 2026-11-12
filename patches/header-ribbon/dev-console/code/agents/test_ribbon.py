"""Widget header ribbon settings (`agents.services.ribbon`). DB-free."""

from types import SimpleNamespace

from django.test import SimpleTestCase

from agents.services.ribbon import (
    RIBBON_ICON_MAX_BYTES,
    RIBBON_TEXT_MAX_LENGTH,
    build_ribbon,
    resolve_icon_img,
)


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

    def test_uploaded_icon_replaces_the_preset(self):
        ribbon = build_ribbon(
            {"ribbon_text": "Hi", "ribbon_icon": "custom"}, icon_img="https://cdn.eka.care/r.png"
        )
        self.assertEqual(ribbon["icon_img"], "https://cdn.eka.care/r.png")
        self.assertNotIn("icon", ribbon)
        # "custom" is not a preset, and no image means no icon at all.
        self.assertNotIn("icon", build_ribbon({"ribbon_text": "Hi", "ribbon_icon": "custom"}))


def _upload(name="r.png", content_type="image/png", size=1000):
    return SimpleNamespace(name=name, content_type=content_type, size=size)


class ResolveIconImgTests(SimpleTestCase):
    def setUp(self):
        self.saved_files = []

        def save(upload):
            self.saved_files.append(upload.name)
            return f"https://cdn.eka.care/{upload.name}"

        self.save = save

    def resolve(self, post, files=None, saved=None):
        return resolve_icon_img(post, files or {}, saved, self.save)

    def test_only_when_upload_your_own_is_picked(self):
        files = {"ribbon_icon_file": _upload()}
        for icon in ("", "gift", "info"):
            self.assertIsNone(self.resolve({"ribbon_icon": icon}, files, saved="https://x/y.png"))
        self.assertEqual(self.saved_files, [])

    def test_new_upload_is_saved_and_wins(self):
        post = {"ribbon_icon": "custom", "ribbon_icon_url": "https://other/a.png"}
        got = self.resolve(post, {"ribbon_icon_file": _upload("new.png")}, saved="https://old/o.png")
        self.assertEqual(got, "https://cdn.eka.care/new.png")
        self.assertEqual(self.saved_files, ["new.png"])

    def test_pasted_https_url_is_used_without_saving(self):
        post = {"ribbon_icon": "custom", "ribbon_icon_url": " https://cdn.eka.care/u.png "}
        self.assertEqual(self.resolve(post, saved="https://old/o.png"), "https://cdn.eka.care/u.png")
        self.assertEqual(self.saved_files, [])

    def test_http_and_other_urls_are_not_accepted(self):
        for bad in ("http://cdn.eka.care/u.png", "javascript:alert(1)", "/media/u.png", "data:image/png;base64,AA"):
            got = self.resolve({"ribbon_icon": "custom", "ribbon_icon_url": bad})
            self.assertIsNone(got)

    def test_keeps_the_saved_icon_when_nothing_new_is_given(self):
        self.assertEqual(
            self.resolve({"ribbon_icon": "custom"}, saved="https://cdn.eka.care/old.png"),
            "https://cdn.eka.care/old.png",
        )
        self.assertIsNone(self.resolve({"ribbon_icon": "custom"}))

    def test_clear_drops_it(self):
        post = {"ribbon_icon": "custom", "clear_ribbon_icon_img": "1"}
        self.assertIsNone(self.resolve(post, {"ribbon_icon_file": _upload()}, saved="https://old/o.png"))
        self.assertEqual(self.saved_files, [])

    def test_rejects_non_images_and_large_files(self):
        post = {"ribbon_icon": "custom"}
        for bad in (
            _upload("a.html", "text/html"),
            _upload("a.png", "image/png", RIBBON_ICON_MAX_BYTES + 1),
        ):
            self.assertIsNone(self.resolve(post, {"ribbon_icon_file": bad}))
        self.assertEqual(self.saved_files, [])
        # A bad upload does not wipe the icon already saved.
        self.assertEqual(
            self.resolve(post, {"ribbon_icon_file": _upload("a.html", "text/html")}, saved="https://old/o.png"),
            "https://old/o.png",
        )
