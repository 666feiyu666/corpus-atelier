"""Package export contracts for the corpus layer and the prompt-session service."""

import unittest

import corpus_atelier.corpus as corpus
from corpus_atelier.app.service import CorpusAtelierApplication
from corpus_atelier.corpus.index import CorpusStore
from corpus_atelier.corpus.ingest import ingest_prompt_session
from corpus_atelier.corpus.records import new_record, normalize_record


class PackageExportTests(unittest.TestCase):
    def test_the_application_service_is_the_public_entry_point(self):
        self.assertTrue(callable(CorpusAtelierApplication))
        for name in (
            "start_from_prompt",
            "start_from_image",
            "attach_session_upload",
            "prepare_image_action",
            "submit_image_action",
            "continue_prompt_session",
            "prompt_session",
        ):
            self.assertTrue(hasattr(CorpusAtelierApplication, name), name)

    def test_corpus_exposes_the_archive_api(self):
        for name in ("TAXONOMY_VERSION", "FACETS", "TAGS", "normalize_tags",
                     "resolve", "tag_ids", "tags_of"):
            self.assertTrue(hasattr(corpus, name), name)
        self.assertTrue(callable(CorpusStore))
        self.assertTrue(callable(ingest_prompt_session))
        self.assertTrue(callable(new_record))
        self.assertTrue(callable(normalize_record))


if __name__ == "__main__":
    unittest.main()
