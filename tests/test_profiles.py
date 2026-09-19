import unittest

from corpus_atelier.design.validation import validate
from corpus_atelier.registry import PROFILES, get_profile


class ProfileTests(unittest.TestCase):
    def test_expected_profiles_are_registered(self):
        self.assertEqual(set(PROFILES), {"rhetoric-poster", "art-article-cover"})
        self.assertNotEqual(
            get_profile("rhetoric-poster").objective,
            get_profile("art-article-cover").objective,
        )

    def test_brief_schemas_are_strict(self):
        profile = get_profile("rhetoric-poster")
        with self.assertRaises(ValueError):
            validate({"topic": "incomplete"}, profile.brief_schema)
