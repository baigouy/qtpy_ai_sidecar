"""Direct categorized selection uses the same selector as discovery, without GUI duplication."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
from mcp.server.fastmcp import FastMCP

prototype=Path(__file__).resolve().parents[2]/'pyfigures_pkg/chatGPT_validation/live_mcp_gui'
if not (prototype/'categorized_mcp.py').exists():
    pytest.skip('Optional PyFigures prototype is not installed',allow_module_level=True)

@pytest.fixture
def selection_server(monkeypatch):
    spec=importlib.util.spec_from_file_location('wording_selection_categories',prototype/'categorized_mcp.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setitem(sys.modules,'original_registry',SimpleNamespace(registry=lambda:{}))
    monkeypatch.setitem(sys.modules,'source_help',SimpleNamespace(explain_feature=lambda topic:None))
    monkeypatch.setitem(sys.modules,'manual_help',SimpleNamespace(explain=lambda topic:{'status':'not_found'}))
    full=FastMCP('selection test')
    calls=[]
    @full.tool()
    def select_live_objects(panel_refs: list[str] | None=None,
                            group_paths: list[list[int]] | None=None,
                            row_numbers: list[int] | None=None, clear: bool=False) -> dict:
        value=dict(panel_refs=panel_refs,group_paths=group_paths,row_numbers=row_numbers,clear=clear)
        calls.append(value)
        return {'document_changed':False,'selection':[] if clear else panel_refs,'arguments':value}
    server=module.build_server(full,lambda *a,**kw:{})
    return server,calls

def test_clear_is_a_top_level_selection_call(selection_server):
    server,calls=selection_server
    tool=server._tool_manager._tools['select_live_objects']
    result=tool.fn(clear=True)
    assert result['selection']==[] and result['document_changed'] is False
    assert calls==[dict(panel_refs=None,group_paths=None,row_numbers=None,clear=True)]
    assert tool.description.startswith('Select OR clear GUI objects. clear=true clears the selection and needs no panel_refs. A selection change, not a document edit.')
    assert set(server._tool_manager._tools)=={'inspect_figure','preview_figure','undo_redo',
        'select_live_objects','list_pyfigures_categories','find_pyfigures_tools','use_pyfigures_tool'}

@pytest.mark.parametrize('arguments',[
    {'panel_refs':['h']}, {'row_numbers':[2]}, {'group_paths':[[1]]}])
def test_direct_selection_keeps_original_arguments(selection_server,arguments):
    server,calls=selection_server
    result=server._tool_manager._tools['select_live_objects'].fn(**arguments)
    assert result['document_changed'] is False
    assert all(calls[0][k]==v for k,v in arguments.items())

def test_selection_remains_searchable_in_layout(selection_server):
    server,calls=selection_server
    result=server._tool_manager._tools['find_pyfigures_tools'].fn(query='clear selection',category='layout')
    item=next(x for x in result['tools'] if x['name']=='select_live_objects')
    assert item['category']=='layout' and item['callable_directly'] is True
    assert 'clear' in item['arguments_schema']['properties']
    assert calls==[]
