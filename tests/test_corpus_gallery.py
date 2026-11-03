"""Gallery seed parsing, import, and retrieval contracts."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from corpus_atelier.corpus.gallery import (
    build_seed,
    ensure_gallery_seed,
    import_seed,
    load_seed,
    packaged_seed_path,
    parse_gallery_markdown,
)
from corpus_atelier.corpus.index import CorpusStore
from corpus_atelier.corpus.taxonomy import resolve, tag_ids


MARKDOWN = """# Watercolor

Range: No. 48–49 · Count: 2

### No. 48 · Dreamy watercolor — young woman at lily pond

- Image: `docs/watercolor/watercolor-lily-pond.png`

  <img src="../../../docs/watercolor/watercolor-lily-pond.png" alt="lily pond" width="420"/>
- Metadata: Watercolor · `portrait` · `1024x1536` · Author: EvoLinkAI · Source: [GitHub archive](https://example.com/prompts)

```text
Dreamy watercolor illustration of a young woman at a lily pond.
```

### No. 49 · Rainy greenhouse

- Metadata: Watercolor · `landscape` · `1536x1024` · Curated

```text
A delicate watercolor illustration of a rainy greenhouse.
```
"""


def _make_image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 96), (30, 60, 90)).save(path, format="PNG")


class GalleryParsingTests(unittest.TestCase):
    def test_markdown_entries_become_structured_records(self):
        entries = parse_gallery_markdown(MARKDOWN, "gallery-watercolor")
        self.assertEqual([entry["number"] for entry in entries], [48, 49])
        first = entries[0]
        self.assertEqual(first["id"], "gallery-no-048")
        self.assertEqual(first["title"], "Dreamy watercolor — young woman at lily pond")
        self.assertEqual(first["image_source"], "docs/watercolor/watercolor-lily-pond.png")
        self.assertEqual(first["size"], "1024x1536")
        self.assertEqual(first["aspect"], "portrait")
        self.assertEqual(first["author"], "EvoLinkAI")
        self.assertEqual(first["source_url"], "https://example.com/prompts")
        self.assertIn("lily pond", first["prompt"])
        self.assertIn("gallery-watercolor", first["tags"])

    def test_entry_without_image_or_author_still_parses(self):
        entries = parse_gallery_markdown(MARKDOWN, "gallery-watercolor")
        second = entries[1]
        self.assertIsNone(second["image_source"])
        self.assertIsNone(second["author"])
        self.assertEqual(second["size"], "1536x1024")

    def test_unknown_collection_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown gallery collection"):
            parse_gallery_markdown(MARKDOWN, "gallery-not-a-collection")

    def test_build_seed_reads_a_gallery_directory(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "gallery-watercolor.md").write_text(MARKDOWN, encoding="utf-8")
            (root / "gallery.md").write_text("# index\n", encoding="utf-8")
            document = build_seed(root)
        self.assertEqual(len(document["records"]), 2)
        self.assertEqual(document["records"][0]["collection"], "gallery-watercolor")


class PackagedSeedTests(unittest.TestCase):
    def test_packaged_seed_is_complete_and_labelled(self):
        document = load_seed(packaged_seed_path())
        records = document["records"]
        self.assertEqual(len(records), 163)
        self.assertEqual([record["number"] for record in records], list(range(1, 164)))
        self.assertEqual(len({record["collection"] for record in records}), 31)
        collections = set(tag_ids("collection"))
        for record in records:
            self.assertIn(record["collection"], collections)
            for tag in record["tags"]:
                self.assertEqual(resolve(tag).id, tag)


class GalleryImportTests(unittest.TestCase):
    def _seed_subset(self):
        document = load_seed(packaged_seed_path())
        return [record for record in document["records"] if record["number"] <= 2]

    def test_import_copies_images_and_is_idempotent(self):
        records = self._seed_subset()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            upstream = root / "upstream"
            media = root / "media"
            _make_image(upstream / records[0]["image_source"])
            store = CorpusStore(root / "corpus.sqlite3")
            try:
                first = import_seed(
                    store, {"records": records},
                    media_root=media, source_root=upstream,
                )
                second = import_seed(
                    store, {"records": records},
                    media_root=media, source_root=upstream,
                )
                stored = store.get(records[0]["id"])
                hits = store.search(tags=[records[0]["collection"]])
            finally:
                store.close()

            self.assertEqual(first.imported, 2)
            self.assertEqual(first.copied_media, 1)
            self.assertEqual(second.copied_media, 0)
            self.assertEqual(len(hits), 2)
            self.assertEqual(stored["source"]["kind"], "import")
            self.assertEqual(stored["source"]["note"], f"No. {records[0]['number']} · {records[0]['title']}")
            self.assertTrue((media / stored["image"]["path"]).is_file())
            self.assertEqual(stored["meta"]["size"], records[0]["size"])

    def test_import_without_source_archives_prompts_only(self):
        records = self._seed_subset()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = CorpusStore(root / "corpus.sqlite3")
            try:
                report = import_seed(
                    store, {"records": records}, media_root=root / "media",
                )
                stored = store.get(records[0]["id"])
            finally:
                store.close()
            self.assertEqual(report.imported, 2)
            self.assertEqual(report.copied_media, 0)
            self.assertEqual(
                len(report.missing_media),
                sum(1 for record in records if record.get("image_source")),
            )
            self.assertIsNone(stored["image"])

    def test_ensure_seed_imports_once(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = CorpusStore(root / "corpus.sqlite3")
            try:
                first = ensure_gallery_seed(store, media_root=root / "media")
                second = ensure_gallery_seed(store, media_root=root / "media")
                count = store.count()
                zh_hits = store.search("水彩", tags=["gallery-watercolor"])
            finally:
                store.close()
            self.assertIsNotNone(first)
            self.assertEqual(first.imported, 163)
            self.assertIsNone(second)
            self.assertEqual(count, 163)
            self.assertEqual([hit["id"] for hit in zh_hits], ["gallery-no-049", "gallery-no-048"])


if __name__ == "__main__":
    unittest.main()
