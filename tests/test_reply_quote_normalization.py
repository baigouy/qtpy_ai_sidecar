"""Pure Python regression tests: typographic quotes do not change reply meaning."""
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('quote_oracle_checks',ROOT/'validation/pyfigures/checks.py')
checks=importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)

class ReplyQuoteNormalizationTests(unittest.TestCase):
    def setUp(self):
        self.before={'letters':{'panels':[],'visible_letter_count':0},
                     'annotations':[],'rows':[],'images':[],
                     'selection':{'selected_panels':[]},
                     'document_digest':'unchanged','caption_digest':None}
    def verify(self,reply,terms,after=None):
        return checks.verify({'no_edit':True,'reply_terms_any':[terms]},
                             self.before,after or copy.deepcopy(self.before),
                             [('assistant',reply)],[])
    def test_curly_apostrophe_matches_ascii_refusal(self):
        self.assertEqual(self.verify("I don\u2019t see a panel labeled aa.",["don't see"]),[])
    def test_ascii_apostrophe_matches_curly_expectation(self):
        self.assertEqual(self.verify("I don't see a panel labeled aa.",["don\u2019t see"]),[])
    def test_double_and_single_typographic_quotes_are_symmetric(self):
        for actual,wanted in [
            ('I cannot find panel \u201caa\u201d.','panel "aa"'),
            ('I cannot find panel "aa".','panel \u201caa\u201d'),
            ('I cannot find panel \u2018aa\u2019.',"panel 'aa'"),
            ("I cannot find panel 'aa'.",'panel \u2018aa\u2019'),
        ]:
            with self.subTest(actual=actual,wanted=wanted):
                self.assertEqual(self.verify(actual,[wanted]),[])
    def test_case_and_comma_spacing_normalization_still_work(self):
        self.assertEqual(self.verify('I DON\u2019T SEE A, B.',["don't see a,b"]),[])
    def test_unrelated_reply_still_fails(self):
        failures=self.verify('Here is panel a.',["don't see"])
        self.assertTrue(any(f.startswith('Missing manual explanation:') for f in failures))
    def test_normalized_quote_cannot_hide_document_mutation(self):
        after=copy.deepcopy(self.before)
        after['document_digest']='changed'
        failures=self.verify('I don\u2019t see panel aa.',["don't see"],after)
        self.assertIn('Saved document_digest changed during a no-edit request',failures)
    def test_normalized_quote_does_not_allow_unrequested_code(self):
        reply='I don\u2019t see panel aa.\n'+chr(96)*3+'\ncode\n'+chr(96)*3
        self.assertIn('Unrequested code in manual help',self.verify(reply,["don't see"]))

if __name__=='__main__':
    import sys
    if any(n=='qtpy' or n.startswith(('PyQt','PySide')) for n in sys.modules):
        raise RuntimeError('Quote tests must remain pure Python; no Qt imports')
    unittest.main()
