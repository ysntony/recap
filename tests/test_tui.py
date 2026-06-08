from __future__ import annotations

import unittest
from io import StringIO
from unittest.mock import patch

from recap.tui import provider_label, render_menu, tui_labels


class TuiTest(unittest.TestCase):
    def test_chinese_labels_after_language_choice(self) -> None:
        labels = tui_labels("chinese")

        self.assertEqual(labels["scope"], "范围")
        self.assertEqual(labels["choose"], "选择 [1]: ")
        self.assertIn("↑/↓", labels["arrow_hint"])
        self.assertEqual(labels["selected"], "已选择：{label}")
        self.assertEqual(labels["using_llm"], "正在使用紧凑 work facts 和所选 LLM provider。")

    def test_bilingual_language_picker_labels(self) -> None:
        labels = tui_labels("bilingual")

        self.assertIn("Choose / 选择", labels["choose"])
        self.assertIn("Use ↑/↓", labels["arrow_hint"])
        self.assertIn("Selected / 已选择", labels["selected"])

    def test_provider_label_is_localized(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertIn("缺少 OPENROUTER_API_KEY", provider_label("openrouter", "chinese"))
            self.assertIn("missing OPENAI_API_KEY", provider_label("openai", "english"))

    def test_arrow_menu_uses_carriage_return_newlines(self) -> None:
        labels = tui_labels("english")
        output = StringIO()

        with patch("sys.stdout", output):
            line_count = render_menu("Pick", [("One", 1), ("Two", 2)], 1, labels)

        self.assertEqual(line_count, 4)
        self.assertIn("\r\n", output.getvalue())
        self.assertNotIn("One\n", output.getvalue())


if __name__ == "__main__":
    unittest.main()
