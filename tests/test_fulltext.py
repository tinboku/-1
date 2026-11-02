"""Offline regression tests for the minimal fulltext/evidence loop."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from dls.config import Config
from dls.fulltext import MAX_PDF_BYTES, download_pdf, extract_sections, extract_text
from dls.llm import HeuristicLLM, OpenAIChatLLM
from dls.models import Paper
from dls.report import generate_report, verify_report
from dls.store import Store


class FulltextTest(unittest.TestCase):
    def setUp(self):
        self.paper = Paper('p1', 'Paper', abstract='Abstract evidence.', key='Ab25',
                           open_access_pdf='https://example.org/paper.pdf')

    def download(self, response=None, error=None):
        session = Mock()
        session.get.side_effect = error
        if response is not None:
            session.get.return_value.__enter__ = Mock(return_value=response)
            session.get.return_value.__exit__ = Mock(return_value=False)
        with patch('dls.fulltext._check_url'), patch('dls.fulltext.requests.Session') as factory:
            factory.return_value.__enter__.return_value = session
            result = download_pdf(self.paper)
        return result, session

    def response(self, body=b'%PDF-test', headers=None):
        response = Mock(is_redirect=False, headers=headers or {'Content-Type': 'application/pdf'})
        response.iter_content.return_value = [body]
        return response

    def test_download_failure_reason(self):
        (data, reason), _ = self.download(error=requests.Timeout('offline timeout'))
        self.assertIsNone(data)
        self.assertIn('offline timeout', reason)

    def test_download_no_url(self):
        self.paper.open_access_pdf = None
        self.assertEqual(download_pdf(self.paper), (None, 'no open_access_pdf URL'))

    def test_download_success_limits_and_headers(self):
        (data, reason), session = self.download(self.response())
        self.assertEqual(data, b'%PDF-test')
        self.assertIsNone(reason)
        self.assertIn('User-Agent', session.get.call_args.kwargs['headers'])
        self.assertTrue(session.get.call_args.kwargs['stream'])
        self.assertIn('timeout', session.get.call_args.kwargs)
        self.assertFalse(session.get.call_args.kwargs['allow_redirects'])

    def test_download_size_type_signature(self):
        cases = [
            (self.response(headers={'Content-Length': str(MAX_PDF_BYTES + 1)}), '20MB'),
            (self.response(body=b'x' * (MAX_PDF_BYTES + 1)), '20MB'),
            (self.response(headers={'Content-Type': 'text/html'}), 'content type'),
            (self.response(body=b'not pdf'), 'signature'),
        ]
        for response, expected in cases:
            with self.subTest(expected=expected):
                (data, reason), _ = self.download(response)
                self.assertIsNone(data)
                self.assertIn(expected, reason)

    def test_private_target_rejected_without_network(self):
        self.paper.open_access_pdf = 'http://127.0.0.1/file.pdf'
        with patch('dls.fulltext.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 80))]), \
                patch('dls.fulltext.requests.Session.get') as get:
            data, reason = download_pdf(self.paper)
        self.assertIsNone(data)
        self.assertIn('private', reason)
        get.assert_not_called()

    def test_redirect_target_checked(self):
        response = self.response(headers={'Location': 'http://127.0.0.1/file.pdf'})
        response.is_redirect = True
        session = Mock()
        session.get.return_value.__enter__ = Mock(return_value=response)
        session.get.return_value.__exit__ = Mock(return_value=False)
        with patch('dls.fulltext._check_url', side_effect=[None, ValueError('private redirect')]) as check, \
                patch('dls.fulltext.requests.Session') as factory:
            factory.return_value.__enter__.return_value = session
            data, reason = download_pdf(self.paper)
        self.assertEqual(check.call_count, 2)
        self.assertIsNone(data)
        self.assertIn('private redirect', reason)
        self.assertEqual(session.get.call_count, 1)

    def test_pypdf_missing(self):
        with patch.dict(sys.modules, {'pypdf': None}):
            self.assertEqual(extract_text(b'%PDF-test'), (None, 'pypdf not installed'))

    def test_parser_success_empty_and_failure(self):
        reader = Mock()
        reader.pages = [Mock(extract_text=lambda: 'Page one'), Mock(extract_text=lambda: 'Page two')]
        module = SimpleNamespace(PdfReader=Mock(return_value=reader))
        with patch.dict(sys.modules, {'pypdf': module}):
            self.assertEqual(extract_text(b'%PDF-test'), ('Page one\n\nPage two', None))
            reader.pages = [Mock(extract_text=lambda: '')]
            self.assertIn('needs_ocr', extract_text(b'%PDF-test')[1])
            module.PdfReader.side_effect = ValueError('damaged PDF')
            self.assertIn('damaged PDF', extract_text(b'bad')[1])

    def test_sections(self):
        text = 'Title\nABSTRACT\nA summary.\n1. Introduction\nIntro.\n2 Materials and Methods\nOur method.\n3 RESULTS\nWe improved accuracy.\n4 Discussion\nLimitations.\nReferences\nRef.'
        sections = extract_sections(text)
        self.assertEqual(sections['methods'], 'Our method.')
        self.assertEqual(sections['results'], 'We improved accuracy.')
        self.assertEqual(sections['references'], 'Ref.')
        self.assertEqual(extract_sections('Unstructured text.'), {'_full': 'Unstructured text.'})

    def test_heuristic_evidence(self):
        sections = {'methods': 'We used a trial. More details.',
                    'results': 'Accuracy improved. Another result.',
                    'discussion': 'This may help. More work needed.'}
        evidence = HeuristicLLM().summarize_evidence(self.paper, sections, 'question')
        self.assertEqual(set(evidence), {'method', 'results', 'conclusion'})
        self.assertEqual(evidence['results']['quote'], 'Accuracy improved.')
        for record in evidence.values():
            self.assertIn(record['quote'], sections[record['section']])
            self.assertLessEqual(len(record['quote']), 200)
            self.assertEqual(record['evidence_scope'], 'fulltext')

    def test_evidence_abstract_missing_and_long_quotes(self):
        llm = HeuristicLLM()
        self.assertEqual(llm.summarize_evidence(self.paper, {}, 'q')['results']['evidence_scope'], 'abstract')
        self.paper.abstract = None
        self.assertEqual(llm.summarize_evidence(self.paper, {}, 'q')['results']['status'], 'unavailable')
        item = llm.summarize_evidence(self.paper, {'results': '文' * 300}, 'q')['results']
        self.assertEqual(len(item['quote']), 200)

    def test_online_evidence_validation_and_visible_fallback(self):
        llm = OpenAIChatLLM(Config())
        item = {'statement': 'Improved accuracy.', 'section': 'results', 'quote': 'Accuracy improved.'}
        data = {k: dict(item) for k in ('method', 'results', 'conclusion')}
        with patch.object(llm, '_chat', return_value=json.dumps(data)) as chat:
            evidence = llm.summarize_evidence(self.paper, {'results': 'Accuracy improved.'}, 'question')
        self.assertEqual(evidence['results']['status'], 'extracted')
        self.assertIn('question', chat.call_args.args[1])
        data['results']['quote'] = 'invented quote'
        with patch.object(llm, '_chat', return_value=json.dumps(data)):
            evidence = llm.summarize_evidence(self.paper, {'results': 'Accuracy improved.'}, 'q')
        self.assertEqual(evidence['results']['quote'], 'Accuracy improved.')
        self.assertIn('untraceable quote', evidence['results']['reason'])


class StoreEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'library.db'
        self.store = Store(self.path)
        self.paper = Paper('p', 'Title', key='Ab25', abstract='An abstract.')
        self.pid = self.store.upsert_paper(self.paper)

    def tearDown(self):
        self.store.conn.close()
        self.tmp.cleanup()

    def test_store_status_roundtrip_and_enrichment(self):
        self.assertEqual(self.store.get_paper(self.pid).fulltext_status, 'none')
        saved = self.store.save_fulltext(self.pid, 'Full text body.')
        self.assertEqual(Path(saved.fulltext_path).parent, (self.path.parent / 'fulltext').resolve())
        self.assertEqual(self.store.read_fulltext(saved), ('Full text body.', None))
        self.store.upsert_paper(Paper('p', 'Title'))
        self.store.conn.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.get_paper(self.pid).fulltext_status, 'ok')
        self.store.save_fulltext(self.pid, None, 'pypdf not installed')
        self.store.conn.close()
        self.store = Store(self.path)
        failed = self.store.get_paper(self.pid)
        self.assertEqual(failed.fulltext_status, 'failed')
        self.assertEqual(failed.fulltext_error, 'pypdf not installed')
        self.assertIsNone(failed.fulltext_path)
        self.assertIsNone(self.store.read_fulltext(failed)[0])

    def test_verify_valid_invalid_unsupported_and_no_citations(self):
        no_evidence = Paper('q', 'No evidence', key='No25', open_access_pdf='https://example.org/a.pdf')
        result = verify_report('Supported [Ab25][Wrong]. No evidence [No25]. Again [Ab25].',
                               [self.paper, no_evidence])
        self.assertEqual(result['total'], 3)
        self.assertEqual(result['traceable'], 1)
        self.assertEqual(result['untraceable'], 2)
        self.assertFalse(result['citations'][1]['exists'])
        self.assertEqual(result['citations'][0]['evidence_scope'], 'abstract')
        empty = verify_report('No citations. [website](https://example.org)', [self.paper])
        self.assertTrue(empty['no_citations'])
        self.assertEqual(empty['total'], 0)

    def test_verify_fulltext_and_missing_cache(self):
        paper = self.store.save_fulltext(self.pid, 'Methods\nOur trial.')
        paper.abstract = None
        self.assertEqual(verify_report('[Ab25]', [paper])['traceable'], 1)
        Path(paper.fulltext_path).unlink()
        result = verify_report('[Ab25]', [paper])
        self.assertEqual(result['traceable'], 0)
        self.assertIn('unavailable', result['citations'][0]['reason'])

    def test_report_saved_with_evidence_and_verification(self):
        self.store.save_fulltext(self.pid, 'Methods\nWe used a trial.\nResults\nAccuracy improved.')
        sid = self.store.create_search('default', 'trial', ['trial'], {})
        self.store.save_results(sid, [self.paper], {self.pid}, {}, None)
        file_id, md = generate_report(self.store, sid, HeuristicLLM())
        self.assertEqual(md, self.store.get_file(file_id)['content'])
        self.assertIn('## 证据核查', md)
        self.assertIn('section=results · 原文：Accuracy improved.', md)
        self.assertIn('evidence_scope=fulltext', md)
        self.assertEqual(verify_report(md, self.store.search_papers(sid))['traceable'], 1)

    def test_no_citation_report_remains_unverifiable_with_appendix(self):
        sid = self.store.create_search('default', 'q', [], {})
        self.store.save_results(sid, [self.paper], {self.pid}, {}, None)
        llm = SimpleNamespace(write_report=lambda *args: '# Uncited report')
        _, md = generate_report(self.store, sid, llm)
        self.assertIn('无引用', md)
        self.assertTrue(verify_report(md, [self.paper])['no_citations'])
