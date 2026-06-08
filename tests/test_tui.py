from __future__ import annotations

import unittest
from unittest.mock import patch

from recap.tui import provider_label, tui_labels


class TuiTest(unittest.TestCase):
    def test_chinese_labels_after_language_choice(self) -> None:
        labels = tui_labels("chinese")

        self.assertEqual(labels["scope"], "范围")
        self.assertEqual(labels["choose"], "选择 [1]: ")
        self.assertEqual(labels["using_llm"], "正在使用紧凑 work facts 和所选 LLM provider。")

    def test_provider_label_is_localized(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertIn("缺少 OPENROUTER_API_KEY", provider_label("openrouter", "chinese"))
            self.assertIn("missing OPENAI_API_KEY", provider_label("openai", "english"))


if __name__ == "__main__":
    unittest.main()
