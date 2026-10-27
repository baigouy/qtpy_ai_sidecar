"""Pure Python tests of the oracle checks added for the coverage cases:
document_contains (row/column label text) and image_field_changed."""
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('coverage_oracle_checks',ROOT/'validation/pyfigures/checks.py')
checks=importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)

class CoverageCheckTests(unittest.TestCase):
    def setUp(self):
        panel={'panel_id':'0/0','letters':[{'text':'f'}],'filename':'f.png'}
        self.before={'letters':{'panels':[panel],'visible_letter_count':1},'annotations':[],'rows':[['f.png']],
                     'images':[{'panel_id':'0/0','LUTs':['MAGENTA','GREEN','BLUE']}],
                     'selection':{'selected_panels':[]},'document_digest':'d','caption_digest':None,
                     'document_strings':['Arial']}
    def verify(self,expect,after,allowed=()):
        return checks.verify(expect,self.before,after,[('assistant','Done.')],list(allowed))
    def test_label_text_found_in_document_strings(self):
        after=copy.deepcopy(self.before)
        after['document_strings']=['Arial','Drug A','Control']
        self.assertEqual(self.verify({'document_contains':['control','Drug A']},after),[])
    def test_missing_label_text_fails(self):
        failures=self.verify({'document_contains':['Rescue']},copy.deepcopy(self.before))
        self.assertIn('Text missing from document: Rescue',failures)
    def test_changed_image_field_passes(self):
        after=copy.deepcopy(self.before)
        after['images'][0]['LUTs']=['GRAY','GRAY','GRAY']
        self.assertEqual(self.verify({'image_field_changed':[{'ref':'f','field':'LUTs'}]},after),[])
    def test_unchanged_image_field_fails(self):
        failures=self.verify({'image_field_changed':[{'ref':'f','field':'LUTs'}]},copy.deepcopy(self.before))
        self.assertIn('Unchanged image LUTs on f',failures)

if __name__=='__main__':
    unittest.main()
