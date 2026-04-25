import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

# Ensure import-time env checks pass on clean machines.
os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("GEMINI_API_KEY", "test-key")

import bot  # noqa: E402


def fake_message(
    text: str = "",
    chat_id: int = 1,
    chat_type: str = "private",
    content_type: str = "text",
    reply_to_message=None,
):
    return SimpleNamespace(
        text=text,
        caption=None,
        chat=SimpleNamespace(id=chat_id, type=chat_type),
        content_type=content_type,
        reply_to_message=reply_to_message,
        location=None,
        contact=None,
        sticker=None,
    )


class BotLogicTests(unittest.TestCase):
    def setUp(self):
        with bot.state_lock:
            bot.ai_history.clear()
            bot.chat_history.clear()
            bot.last_user_seen_at.clear()
            bot.last_user_signature.clear()
            bot.user_repeat_count.clear()
            bot.sulky_until.clear()

    def test_trigger_precision_regression(self):
        self.assertTrue(bot.has_neari_call("hello neari"))
        self.assertTrue(bot.has_neari_call("សួស្តី នារី"))
        self.assertFalse(bot.has_neari_call("sneari123"))
        self.assertFalse(bot.has_angry_trigger("hello friend, have a nice day"))
        self.assertFalse(bot.has_shy_trigger("lovely weather"))  # no exact "love" token

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

    def test_ai_memory_continuity_turn2_contains_turn1(self):
        msg = fake_message(chat_id=99, text="/ai first")

        calls = []

        def fake_generate(task_text, system_instruction, **kwargs):
            calls.append(task_text)
            return ("answer", "model-x")

        with patch.object(bot, "send_typing"), patch.object(bot, "send_text"), patch.object(
            bot, "generate_task_with_fallback", side_effect=fake_generate
        ):
            bot.run_ai_mode(msg, "first question")
            bot.run_ai_mode(msg, "second question")

        self.assertEqual(len(calls), 2)
        second_task = calls[1]
        self.assertIn("User: first question", second_task)
        self.assertIn("Assistant: answer", second_task)
        self.assertIn("User: second question", second_task)

    def test_group_reply_gating(self):
        msg_group_plain = fake_message("hello", chat_type="group")
        msg_group_name = fake_message("hey neari", chat_type="group")

        with patch.object(bot, "is_reply_to_this_bot", return_value=False):
            self.assertFalse(bot.should_respond_in_group(msg_group_plain, "hello"))
            self.assertTrue(bot.should_respond_in_group(msg_group_name, "hey neari"))

    def test_reply_pipeline_skips_when_group_not_addressed(self):
        msg = fake_message("hello", chat_type="group")
        with patch.object(bot, "should_respond_in_group", return_value=False), patch.object(
            bot, "generate_with_fallback"
        ) as gen:
            bot.reply(msg)
            gen.assert_not_called()

    def test_translate_full_text_retries_chunk_once(self):
        payload = "one short sentence."
        side_effects = [RuntimeError("temp"), ("translated ok", "m1")]

        with patch.object(bot, "generate_task_with_fallback", side_effect=side_effects):
            out, model = bot.translate_full_text(payload, "Khmer")

        self.assertEqual(out, "translated ok")
        self.assertEqual(model, "m1")

    def test_translate_full_text_persistent_failure_marks_chunk(self):
        payload = "one short sentence."
        with patch.object(bot, "generate_task_with_fallback", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError) as ctx:
                bot.translate_full_text(payload, "Khmer")
        self.assertTrue(str(ctx.exception).startswith("translate_chunk_failed:1:"))

    def test_translate_command_chunk_error_user_message(self):
        msg = fake_message("/tr hello", chat_id=55)
        sent = []
        with patch.object(
            bot,
            "translate_full_text",
            side_effect=RuntimeError("translate_chunk_failed:2:boom"),
        ), patch.object(bot, "send_typing"), patch.object(
            bot, "send_text", side_effect=lambda _m, text, **_k: sent.append(text)
        ):
            bot.translate_command(msg)
        self.assertTrue(any("part 2" in s.lower() for s in sent))


if __name__ == "__main__":
    unittest.main()

