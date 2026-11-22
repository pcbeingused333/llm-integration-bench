"""What the diff classifier decides. Run with: python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import classify  # noqa: E402


def fix(title, patch, name="src/app.py", tests=()):
    return {"title": title, "test_files": list(tests),
            "files": [{"filename": name, "patch": patch}]}


class Classify(unittest.TestCase):
    def test_a_fix_with_no_llm_in_it_is_not_provider_facing_whatever_the_title_says(self):
        rec = fix("fix: error when the matrix fails to parse",
                  "@@\n-limit = 10\n+limit = 64\n")
        self.assertEqual(classify.classify(rec)[0], classify.NOT_PROVIDER)

    def test_a_retired_model_id_replaced_in_a_default_is_a_retired_default(self):
        rec = fix("fix: default the Anthropic model to claude-sonnet-5-5",
                  '@@\n-model = "claude-sonnet-4-5"\n+model = "claude-sonnet-5-5"\n')
        self.assertEqual(classify.classify(rec)[0], "Retired model defaults")

    def test_streamed_tool_call_deltas_are_streaming_and_tool_calls(self):
        rec = fix("keep streamed tool calls apart",
                  "@@\n-    for delta in chunk.delta.tool_calls:\n+    for delta in chunk.delta.tool_calls:\n+        index = delta.index\n")
        self.assertEqual(classify.classify(rec)[0], "Streaming and tool calls")

    def test_only_tests_and_docs_changed_is_documentation(self):
        rec = {"title": "docs: replace retired model", "test_files": [],
               "files": [{"filename": "README.md", "patch": "@@\n-gpt-4\n+gpt-5\n"}]}
        self.assertEqual(classify.classify(rec)[0], "Documentation")

    def test_a_word_that_is_only_english_does_not_make_a_fix_provider_facing(self):
        rec = fix("fix async pipeline error messages embedding the args tuple",
                  "@@\n-msg = f'{exception.args}'\n+msg = f'{exception.args[0]}'\n")
        self.assertEqual(classify.classify(rec)[0], classify.NOT_PROVIDER)


if __name__ == "__main__":
    unittest.main()
