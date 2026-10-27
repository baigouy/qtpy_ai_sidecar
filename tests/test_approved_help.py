"""Source-only checks for approved arrowhead and drag-help descriptions."""
import ast,importlib.util,sys
from pathlib import Path
import pytest

prototype=Path(__file__).resolve().parents[2]/'pyfigures_pkg/chatGPT_validation/live_mcp_gui'
if not prototype.exists():pytest.skip('Optional PyFigures prototype absent',allow_module_level=True)

def test_arrowhead_description_keeps_native_direction_encoding():
    tree=ast.parse((prototype/'original_registry.py').read_text(encoding='utf-8'))
    docs=[]
    for node in ast.walk(tree):
        if isinstance(node,ast.Dict):
            for key,value in zip(node.keys,node.values):
                if isinstance(key,ast.Constant) and key.value=='add_arrow' and isinstance(value,ast.Constant):
                    docs.append(value.value)
    assert any("style='arrowhead'" in s and "kind='arrowhead'" in s and 'Do not collapse endpoints' in s for s in docs)

def test_reviewed_drag_guide_explains_nesting_in_existing_group(monkeypatch):
    monkeypatch.syspath_prepend(str(prototype))
    spec=importlib.util.spec_from_file_location('fresh_drag_help_tests',prototype/'manual_help.py')
    help=importlib.util.module_from_spec(spec);spec.loader.exec_module(help)
    import json
    assert help.fingerprints()==json.loads((prototype/'manual_help_verified.json').read_text(encoding='utf-8'))
    answer=help.explain('drag_and_drop')
    assert answer['status']=='source_reviewed'
    steps=' '.join(step for guide in answer['guides'] for step in guide['steps'])
    assert 'Stack with it (column in the row)' in steps
    assert 'Beside it (row in the column)' in steps
    assert 'target' in steps and 'slot' in steps
