"""Closed-taxonomy invariants for the corpus layer."""

import unittest

from corpus_atelier.corpus.taxonomy import (
    FACETS,
    TAXONOMY_VERSION,
    TAGS,
    normalize_tags,
    resolve,
    tag_ids,
    tags_of,
)


class TaxonomyTests(unittest.TestCase):
    def test_version_is_set(self):
        self.assertTrue(TAXONOMY_VERSION)

    def test_every_tag_is_faceted_and_labelled(self):
        self.assertGreater(len(TAGS), 0)
        for tag in TAGS.values():
            self.assertIn(tag.facet, FACETS)
            self.assertTrue(tag.id)
            self.assertTrue(tag.en)
            self.assertTrue(tag.zh)

    def test_movements_mirror_packaged_references(self):
        art = {tag.id for tag in tags_of("art_movement")}
        design = {tag.id for tag in tags_of("design_movement")}
        self.assertEqual(art, {
            "neoclassicism", "romanticism", "realism", "impressionism",
            "post-impressionism", "expressionism", "surrealism",
        })
        self.assertEqual(design, {
            "art-nouveau", "constructivism", "de-stijl",
            "bauhaus-new-typography", "swiss-style", "art-deco",
            "psychedelic", "postmodern-memphis",
        })

    def test_objective_facet_is_retired(self):
        self.assertNotIn("objective", FACETS)
        self.assertNotIn("rhetoric-led", TAGS)
        self.assertNotIn("art-led", TAGS)

    def test_tag_ids_filter_by_facet(self):
        self.assertEqual(len(tag_ids()), len(TAGS))
        self.assertEqual(tag_ids("use_case"), [tag.id for tag in tags_of("use_case")])

    def test_normalize_tags_dedups_and_preserves_order(self):
        self.assertEqual(
            normalize_tags(["poster", "warm", "poster", "surrealism"]),
            ["poster", "warm", "surrealism"],
        )

    def test_normalize_tags_rejects_unknown(self):
        with self.assertRaises(ValueError):
            normalize_tags(["poster", "not-a-real-tag"])

    def test_resolve_returns_tag(self):
        tag = resolve("swiss-style")
        self.assertEqual(tag.facet, "design_movement")
        self.assertEqual(tag.en, "Swiss Style")
        self.assertEqual(tag.zh, "瑞士风格")

    def test_resolve_rejects_unknown(self):
        with self.assertRaises(ValueError):
            resolve("nope")
