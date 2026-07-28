import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent.ci_runner import CIRunner


class CIRunnerTests(unittest.TestCase):
    @patch("agent.ci_runner.API_KEY", "token")
    @patch("agent.ci_runner.OpenAI")
    def test_upload_files_missing_path_raises(self, openai_cls):
        runner = CIRunner()
        runner.client = openai_cls.return_value

        with self.assertRaises(RuntimeError):
            runner.upload_files(["C:/missing/file.csv"])

    @patch("agent.ci_runner.API_KEY", "token")
    @patch("agent.ci_runner.OpenAI")
    def test_partial_upload_cleans_remote_files(self, openai_cls):
        client = openai_cls.return_value
        client.files.create.side_effect = [
            SimpleNamespace(id="file-1"),
            RuntimeError("boom"),
        ]
        client.files.delete = MagicMock()
        runner = CIRunner()
        runner.client = client

        with tempfile.TemporaryDirectory() as tmpdir:
            first = os.path.join(tmpdir, "a.csv")
            second = os.path.join(tmpdir, "b.csv")
            with open(first, "w", encoding="utf-8") as handle:
                handle.write("a\n1\n")
            with open(second, "w", encoding="utf-8") as handle:
                handle.write("b\n2\n")

            with self.assertRaises(RuntimeError):
                runner.upload_files([first, second])

        client.files.delete.assert_called_once_with("file-1")
        self.assertEqual(runner.file_ids, [])


if __name__ == "__main__":
    unittest.main()
