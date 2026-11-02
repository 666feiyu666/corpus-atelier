"""Retrieval regression benchmark must pass as a whole."""

import tempfile
import unittest
from pathlib import Path

from corpus_atelier.corpus.eval import run_eval
from corpus_atelier.corpus.index import CorpusStore


class RetrievalEvalTests(unittest.TestCase):
    def test_benchmark_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CorpusStore(Path(tmp) / "corpus.sqlite3")
            try:
                summary = run_eval(store)
            finally:
                store.close()
        self.assertEqual(summary["passed"], summary["total"], summary)


if __name__ == "__main__":
    unittest.main()
