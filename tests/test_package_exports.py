"""Package export contracts for the corpus and atelier layers."""

import unittest

import corpus_atelier.atelier as atelier
import corpus_atelier.corpus as corpus
from corpus_atelier.corpus.index import CorpusStore
from corpus_atelier.corpus.ingest import ingest_run
from corpus_atelier.corpus.records import new_record, normalize_record


class PackageExportTests(unittest.TestCase):
    def test_atelier_exposes_the_generation_api(self):
        for name in (
            "compile_design_direction_prompt",
            "synthesize_design_directions",
            "compile_design_implementation_prompt",
            "synthesize_design_implementation",
            "compile_generation_prompt",
            "compile_image_prompt_prompt",
            "synthesize_image_prompt",
            "compile_intake_prompt",
            "reverse_prompt",
            "reverse_prompt_instruction",
        ):
            self.assertTrue(hasattr(atelier, name), name)

    def test_corpus_exposes_the_archive_api(self):
        for name in ("TAXONOMY_VERSION", "FACETS", "TAGS", "normalize_tags",
                     "resolve", "tag_ids", "tags_of"):
            self.assertTrue(hasattr(corpus, name), name)
        self.assertTrue(callable(CorpusStore))
        self.assertTrue(callable(ingest_run))
        self.assertTrue(callable(new_record))
        self.assertTrue(callable(normalize_record))


if __name__ == "__main__":
    unittest.main()
