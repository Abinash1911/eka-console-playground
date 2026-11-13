"""Widget banner text (`agents.services.banner`). DB-free."""

from django.test import SimpleTestCase

from agents.services.banner import BANNER_MAX_LENGTH, clean_banner


class CleanBannerTests(SimpleTestCase):
    def test_no_text_means_no_banner(self):
        for empty in (None, "", "   ", "\n\t "):
            self.assertIsNone(clean_banner(empty))

    def test_keeps_the_text_trimmed(self):
        self.assertEqual(clean_banner("  Chat and earn coins "), "Chat and earn coins")

    def test_is_one_line(self):
        self.assertEqual(clean_banner("Chat\nand   earn\r\ncoins"), "Chat and earn coins")

    def test_cut_at_the_limit_spaces_included(self):
        self.assertEqual(BANNER_MAX_LENGTH, 200)
        self.assertEqual(len(clean_banner("x" * 250)), 200)
        self.assertEqual(len(clean_banner("a " * 150)), 199)  # 200 chars, trailing space trimmed
        self.assertEqual(len(clean_banner("x" * 200)), 200)

    def test_keeps_non_english_and_symbols(self):
        self.assertEqual(clean_banner("2 संदेश भेजें, ₹20 पाएं"), "2 संदेश भेजें, ₹20 पाएं")
