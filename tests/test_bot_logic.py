import os
import unittest

# Ensure import-time env checks pass even on clean machines.
os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("GEMINI_API_KEY", "test-key")

import bot  # noqa: E402


class BotLogicTests(unittest.TestCase):
    def test_has_neari_call_word_boundary(self):
        self.assertTrue(bot.has_neari_call("hello neari"))
        self.assertTrue(bot.has_neari_call("សួស្តី នារី"))
        self.assertFalse(bot.has_neari_call("sneari123"))

    def test_clean_ai_output_mode_aware(self):
        text = "```python\nprint('hi')\n``` **bold**"
        plain = bot.clean_ai_output(text, sanitize_markdown=True)
        keep = bot.clean_ai_output(text, sanitize_markdown=False)
        self.assertNotIn("```", plain)
        self.assertNotIn("**", plain)
        self.assertIn("```python", keep)
        self.assertIn("**bold**", keep)

    def test_split_translation_chunks(self):
        src = ("A. " * 500).strip()
        chunks = bot.split_translation_chunks(src, 200)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(0 < len(c) <= 200 for c in chunks))

    def test_wants_long_response(self):
        self.assertTrue(bot.wants_long_response("please explain in detail step by step"))
        self.assertTrue(bot.wants_long_response("សូមពន្យល់លម្អិតជំហានៗ"))
        self.assertFalse(bot.wants_long_response("ok"))


if __name__ == "__main__":
    unittest.main()

