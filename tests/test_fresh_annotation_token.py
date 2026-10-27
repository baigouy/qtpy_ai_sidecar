"""Pure host-state tests. No GUI/HTTP/model; run against a shadow adapter."""
import copy,importlib.util,os
from pathlib import Path
import unittest
target=Path(os.environ.get('SIDECAR_ADAPTER_UNDER_TEST', str(Path(__file__).resolve().parents[1]/'src/qtpy_ai_sidecar/adapters/pyfigures.py')))
spec=importlib.util.spec_from_file_location('token_adapter_subject',target)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class TokenFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.old={'panel_references':[{'panel_id':'1/3','letters':['h']}],
                  'text_annotations':[{'panel_id':'1/3','annotation_index':1,'token':'old','text':'control'}],
                  'roi_annotations':[],'selection':{'selected_panels':[]}}
        self.fresh=copy.deepcopy(self.old)
        self.fresh['text_annotations'][0].update(token='new',text='treated')
        self.adapter=module.PyFiguresAdapter('unused')
        self.reads=[]
        def context():
            self.reads.append(True)
            return copy.deepcopy(self.fresh)
        self.adapter.context=context
    def call(self,token):
        args={'tool_name':'edit_annotation_properties','arguments':{
            'panel_ref':'h','annotation_index':1,'token':token,'changes':{'placement':'bottom right'}}}
        before=copy.deepcopy(args)
        try:
            self.adapter.validate_tool_call('use_pyfigures_tool',args,self.old,'Move the text on panel h to the bottom right.')
        finally:self.assertEqual(args,before)
    def test_fresh_object_token_after_prior_edit_is_not_rejected(self):
        self.call('new')
        self.assertEqual(self.reads,[True])
    def test_old_token_is_refused_with_the_current_object_token(self):
        with self.assertRaisesRegex(ValueError,'token=new'):
            self.call('old')
    def test_no_token_is_still_refused_never_filled_silently(self):
        with self.assertRaisesRegex(ValueError,'token=new'):
            self.call(None)
    def test_other_operations_do_not_add_a_host_read(self):
        self.adapter.validate_tool_call('inspect_figure',{},self.old,'Inspect the figure.')
        self.assertEqual(self.reads,[])
if __name__=='__main__':unittest.main()
