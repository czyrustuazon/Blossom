import tempfile
import unittest
from pathlib import Path

from blossom_eval.apply import extract_file_writes
from blossom_eval.corpus import build_user_prompt, load_corpus
from blossom_eval.harness import run_task
from blossom_eval.scorers import run_check
from blossom_eval.store import EvalStore


class EvalHarnessTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent
        self.corpus_dir = self.root / "corpora" / "php-modernization"

    def test_load_php_corpus(self):
        corpus = load_corpus(self.corpus_dir)
        self.assertEqual(corpus.id, "php-modernization")
        self.assertGreaterEqual(len(corpus.tasks), 1)

    def test_extract_file_writes(self):
        text = 'Here\n```php path=login.php\n<?php echo 1;\n```'
        writes = extract_file_writes(text)
        self.assertIn("login.php", writes)

    def test_build_user_prompt_includes_fixture(self):
        corpus = load_corpus(self.corpus_dir)
        task = corpus.tasks[0]
        with tempfile.TemporaryDirectory() as tmp:
            prompt = build_user_prompt(task, Path(tmp))
        self.assertIn("mysql_connect", prompt)
        self.assertIn("<<<FILE", prompt)

    def test_dry_run_records_failure_on_baseline(self):
        corpus = load_corpus(self.corpus_dir)
        task = corpus.tasks[0]
        with tempfile.TemporaryDirectory() as tmp:
            db = EvalStore(Path(tmp) / "eval.db")
            result = run_task(corpus, task, dry_run=True)
            self.assertFalse(result.passed)
            db.record(
                corpus_id=corpus.id,
                task_id=task.id,
                task_title=task.title,
                domain="php",
                mode=task.mode,
                passed=result.passed,
                written_files=result.written_files,
                check_results=result.check_results,
                response_chars=result.response_chars,
            )
            total, passed, _rate = db.pass_rate(corpus.id)
            self.assertEqual(total, 1)
            self.assertEqual(passed, 0)

    def test_response_regex_check(self):
        check = type("C", (), {})()
        from blossom_eval.corpus import CheckSpec

        spec = CheckSpec(
            id="hex",
            type="response_regex",
            pattern=r"0x[0-9a-f]+",
        )
        ok = run_check(spec, work_dir=Path("."), response_text="found at 0x80123456")
        self.assertTrue(ok.passed)


if __name__ == "__main__":
    unittest.main()
