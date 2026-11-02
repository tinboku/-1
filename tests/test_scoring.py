import unittest

from dls.models import Paper
from dls.scoring import dedupe, heuristic_match, make_key

CRITERIA = [
    "natural-language descriptions of tabular datasets using large language "
    "models, including data profiling and metadata generation"
]


def paper(pid, title, abstract, year=2025, cites=10, doi=None, source="semantic_scholar"):
    return Paper(
        paper_id=pid, title=title, abstract=abstract, year=year,
        authors=["Alice Zhang"], citation_count=cites, doi=doi, source=source,
    )


class TestKeys(unittest.TestCase):
    def test_basic_key(self):
        taken: set[str] = set()
        p = paper("x", "Some Title", "", year=2025)
        self.assertEqual(make_key(p, taken), "Zhang25")

    def test_collision_suffix_b(self):
        taken: set[str] = set()
        p1 = paper("x", "T1", "", year=2026)
        p2 = paper("y", "T2", "", year=2026)
        self.assertEqual(make_key(p1, taken), "Zhang26")
        self.assertEqual(make_key(p2, taken), "Zhang26b")


class TestDedupe(unittest.TestCase):
    def test_merge_by_doi(self):
        a = paper("s2-1", "Same Paper", None, doi="10.1/abc")
        b = paper("W123", "Same Paper", "now with abstract", doi="10.1/abc", source="openalex")
        out = dedupe([a, b])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].abstract, "now with abstract")
        self.assertIn("openalex", out[0].sources)
        self.assertIn("semantic_scholar", out[0].sources)


class TestHeuristicMatch(unittest.TestCase):
    def test_relevant_beats_irrelevant(self):
        rel = paper(
            "r",
            "Generating natural language descriptions of tabular datasets with large language models",
            "We generate natural language descriptions of tabular datasets using large "
            "language models, data profiling and metadata generation for dataset catalogs.",
            cites=40,
        )
        irr = paper(
            "i",
            "Quantum error correction with surface codes",
            "We study quantum error correction and fault tolerant quantum computation.",
            cites=900,
        )
        s_rel, _ = heuristic_match(CRITERIA, rel)
        s_irr, _ = heuristic_match(CRITERIA, irr)
        self.assertGreater(s_rel, 55)
        self.assertLess(s_irr, 55)
        self.assertGreater(s_rel, s_irr)


if __name__ == "__main__":
    unittest.main()
