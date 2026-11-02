import tempfile
import unittest
from pathlib import Path

from dls.engine import DeepSearchEngine
from dls.llm import HeuristicLLM
from dls.models import Paper
from dls.store import Store

CRITERIA = [
    "natural-language descriptions of tabular datasets using large language "
    "models, including data profiling and metadata generation for catalogs"
]
ABSTRACT = (
    "We generate natural language descriptions of tabular datasets using large "
    "language models, with data profiling and metadata generation for dataset "
    "catalogs and discovery."
)


def mk(pid, title, abstract=ABSTRACT, year=2025, cites=30, doi=None, source="semantic_scholar", authors=None):
    return Paper(
        paper_id=pid, title=title, abstract=abstract, year=year,
        authors=authors or ["Alice Zhang"], citation_count=cites, doi=doi, source=source,
    )


P1 = mk("s2-1", "AutoDDG: Automated Dataset Description Generation", doi="10.1/a")
P2_S2 = mk("s2-2", "Polaris: Structured Dataset Descriptions", year=2026, cites=5, doi="10.1/b")
P2_OA = mk("W2", "Polaris: Structured Dataset Descriptions", year=2026, cites=5, doi="10.1/b", source="openalex")
P3 = mk(
    "s2-3", "Quantum error correction with surface codes",
    abstract="Fault tolerant quantum computation with surface codes and decoders.",
    year=2024, cites=900,
)
P4 = mk("s2-4", "Dataset Metadata Generation for Catalogs", year=2023, cites=12, doi="10.1/d")
P5 = mk("W5", "Metadata Generation for Dataset Discovery", year=2026, cites=3, source="openalex")
P6 = mk("W6", "Tabular Dataset Descriptions with Language Models", year=2026, cites=2, source="openalex")


class FakeS2:
    def search(self, query, limit=50, offset=0, year=None):
        return [P1, P2_S2, P3]

    def citations(self, paper_id, limit=50):
        return [P4] if paper_id == "s2-1" else []

    def references(self, paper_id, limit=50):
        return []


class FakeOpenAlex:
    def search(self, query, per_page=25):
        return [P2_OA, P5, P6]


class TestEngine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "test.db")
        self.engine = DeepSearchEngine(FakeS2(), FakeOpenAlex(), HeuristicLLM(), self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_full_run(self):
        outcome = self.engine.run("dataset descriptions with LLMs", CRITERIA, per_query=10)
        # Included: P1, P2 (merged), P5, P6 from search + P4 from snowballing. P3 excluded.
        self.assertEqual(outcome.found, 5)
        self.assertEqual(outcome.excluded_count, 1)
        self.assertTrue(outcome.converged)
        self.assertGreaterEqual(outcome.rounds, 1)
        titles = [p.title for p in outcome.included]
        self.assertTrue(any("AutoDDG" in t for t in titles))
        self.assertTrue(any("Metadata Generation for Catalogs" in t for t in titles))
        # Provenance: the snowballed paper records which seed it came from.
        snowballed = [p for p in outcome.included if "Catalogs" in p.title][0]
        self.assertEqual(snowballed.found_via, "citations of [Zhang25]")
        stored_snow = [p for p in self.store.search_papers(outcome.search_id) if "Catalogs" in p.title][0]
        self.assertEqual(stored_snow.found_via, "citations of [Zhang25]")
        for p in outcome.included:
            self.assertIsNotNone(p.key)
            self.assertGreaterEqual(p.match, 55)
        # Coverage: S2 relevant {P1,P2,P4}=3, OA relevant {P2,P5,P6}=3, overlap {P2}=1
        self.assertIsNotNone(outcome.coverage)
        self.assertAlmostEqual(outcome.coverage["estimated_total_relevant"], 7.0)
        self.assertAlmostEqual(outcome.coverage["estimated_coverage"], 5 / 7, places=3)
        # Persisted
        stored = self.store.search_papers(outcome.search_id, included_only=True)
        self.assertEqual(len(stored), 5)
        search = self.store.get_search(outcome.search_id)
        self.assertEqual(search["counts"]["found"], 5)


class FakeS2Clone:
    """Returns the seed paper again under a different id (cross-source clone)."""

    def search(self, query, limit=50, offset=0, year=None):
        return [P1]

    def citations(self, paper_id, limit=50):
        clone = mk("doi:10.1/a", P1.title, year=2025, cites=30, doi="10.1/a", source="crossref")
        return [clone]

    def references(self, paper_id, limit=50):
        return []


class TestCrossSourceDedup(unittest.TestCase):
    def test_clone_not_double_counted(self):
        with tempfile.TemporaryDirectory() as td:
            store = Store(Path(td) / "t.db")
            engine = DeepSearchEngine(FakeS2Clone(), None, HeuristicLLM(), store)
            outcome = engine.run("dataset descriptions with LLMs", CRITERIA, per_query=10)
            self.assertEqual(outcome.found, 1)
            self.assertEqual(outcome.included[0].title, P1.title)


class TestTrace(unittest.TestCase):
    def test_trace_from_seed(self):
        with tempfile.TemporaryDirectory() as td:
            store = Store(Path(td) / "t.db")
            engine = DeepSearchEngine(FakeS2(), None, HeuristicLLM(), store)
            seed = mk("s2-1", "AutoDDG: Automated Dataset Description Generation", doi="10.1/a")
            outcome = engine.trace(seed, question=CRITERIA[0])
            # FakeS2.citations(s2-1) -> [P4]; references -> [].
            self.assertEqual(outcome.found, 1)
            self.assertEqual(outcome.included[0].title, P4.title)
            self.assertEqual(outcome.included[0].found_via, "citations of [Zhang25]")


if __name__ == "__main__":
    unittest.main()
