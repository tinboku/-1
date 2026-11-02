import tempfile
import unittest
from pathlib import Path

from dls.importers import parse_bibtex
from dls.models import Paper
from dls.report import papers_to_bibtex, papers_to_csv, papers_to_ris
from dls.store import Store

BIB = """
@article{zhang2025autoddg,
  title = {AutoDDG: Automated Dataset Description Generation},
  author = {Alice Zhang and Bob Li},
  year = {2025},
  journal = {Proc. ACM},
  doi = {10.1/a}
}
@inproceedings{li2026polaris,
  title = {Polaris: Structured Dataset Descriptions},
  author = {Bob Li},
  year = {2026},
  booktitle = {ICDE},
  doi = {10.1/b}
}
"""


class TestBibtex(unittest.TestCase):
    def test_parse(self):
        papers = parse_bibtex(BIB)
        self.assertEqual(len(papers), 2)
        self.assertEqual(papers[0].authors, ["Alice Zhang", "Bob Li"])
        self.assertEqual(papers[0].year, 2025)
        self.assertEqual(papers[0].doi, "10.1/a")
        self.assertEqual(papers[1].venue, "ICDE")


class TestExports(unittest.TestCase):
    def setUp(self):
        self.paper = Paper(
            paper_id="s2-1", title="AutoDDG", year=2025, authors=["Alice Zhang"],
            venue="Proc. ACM", doi="10.1/a", citation_count=100,
        )
        self.paper.key = "Zhang25"

    def test_bibtex(self):
        out = papers_to_bibtex([self.paper])
        self.assertIn("@article{Zhang25", out)
        self.assertIn("doi = {10.1/a}", out)

    def test_csv(self):
        out = papers_to_csv([self.paper])
        self.assertIn("Zhang25", out)
        self.assertIn("AutoDDG", out)

    def test_ris(self):
        out = papers_to_ris([self.paper])
        self.assertIn("TY  - JOUR", out)
        self.assertIn("DO  - 10.1/a", out)


class TestStore(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            store = Store(Path(td) / "t.db")
            p = Paper(paper_id="s2-9", title="A Paper", year=2024, authors=["Carol Dan"], citation_count=7)
            db_id = store.upsert_paper(p)
            self.assertEqual(p.key, "Dan24")
            store.set_star(db_id, True)
            store.set_folder(db_id, "core")
            starred = store.list_papers(starred_only=True)
            self.assertEqual(len(starred), 1)
            found = store.find_paper("Dan24")
            self.assertIsNotNone(found)
            self.assertEqual(found.title, "A Paper")
            self.assertEqual(store.find_paper("10.1/none"), None)


if __name__ == "__main__":
    unittest.main()
