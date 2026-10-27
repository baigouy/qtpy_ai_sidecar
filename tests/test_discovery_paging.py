"""Discovery keeps concrete operations visible and pages complete schemas."""
import importlib.util
from pathlib import Path
import sys,types,json
import pytest

def server(monkeypatch):
    from mcp.server.fastmcp import FastMCP
    path=Path(__file__).resolve().parents[2]/'pyfigures_pkg/chatGPT_validation/live_mcp_gui/categorized_mcp.py'
    if not path.exists():pytest.skip('Optional PyFigures prototype integration is not installed')
    spec=importlib.util.spec_from_file_location('discovery_under_test',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    full=FastMCP('test')
    def sample(value:str=''):
        return {}
    for name in ('export_figure','set_figure_caption','get_figure_caption','set_scale_bar','set_scale_bar_all','get_annotations','add_image'):
        full.add_tool(sample,name=name,description=('Export PNG SVG PDF file' if name=='export_figure' else name.replace('_',' ')))
    registry=types.ModuleType('original_registry')
    registry.registry=lambda:{n:None for n in full._tool_manager._tools}
    monkeypatch.setitem(sys.modules,'original_registry',registry)
    source=types.ModuleType('source_help');source.explain_feature=lambda q:None
    monkeypatch.setitem(sys.modules,'source_help',source)
    help=types.ModuleType('manual_help');help.explain=lambda q:{'status':'unknown_operation'}
    monkeypatch.setitem(sys.modules,'manual_help',help)
    return module.build_server(full,lambda *a:{}),full

def test_concrete_export_outranks_generic_figure(monkeypatch):
    s,_=server(monkeypatch)
    result=s._tool_manager._tools['find_pyfigures_tools'].fn(query='export save png figure')
    assert result['tools'][0]['name']=='export_figure'

def test_single_scale_bar_is_default_bulk_is_explicit(monkeypatch):
    s,_=server(monkeypatch);find=s._tool_manager._tools['find_pyfigures_tools'].fn
    assert find(query='scale bar')['tools'][0]['name']=='set_scale_bar'
    assert find(query='all scale bars')['tools'][0]['name']=='set_scale_bar_all'

def test_caption_metadata_is_discoverable(monkeypatch):
    s,_=server(monkeypatch)
    assert s._tool_manager._tools['find_pyfigures_tools'].fn(query='caption')['tools'][0]['name']=='set_figure_caption'

def test_pagination_returns_whole_schema_entries(monkeypatch):
    s,full=server(monkeypatch)
    # The server retains the tool objects; exercise large documentation results.
    for tool in full._tool_manager._tools.values():tool.description='documentation '*650
    find=s._tool_manager._tools['find_pyfigures_tools'].fn
    result=find(query='',limit=12)
    assert result['next_offset'] in (None,len(result['tools']))
    assert len(json.dumps(result))<24000
    full_entries=[e for e in result['tools'] if 'arguments_schema' in e]
    assert 1<=len(full_entries)<=2                    # compact: best matches carry the schema
    for entry in full_entries:assert entry['arguments_schema']['type']=='object'
    for entry in result['tools']:
        if 'arguments_schema' not in entry:assert entry['summary'] and entry['name'] in entry['schema']

def test_common_contracts_off_by_default_and_scoped_when_on(monkeypatch):
    monkeypatch.delenv('PYFIGURES_COMMON_CONTRACTS',raising=False)
    s,_=server(monkeypatch)
    assert 'Common exact contracts' in s._tool_manager._tools['use_pyfigures_tool'].description
    assert 'except the common operations' not in s.instructions
    monkeypatch.setenv('PYFIGURES_COMMON_CONTRACTS','1')
    s,_=server(monkeypatch)
    text=s._tool_manager._tools['use_pyfigures_tool'].description
    assert 'call them through use_pyfigures_tool' in text and 'callable directly' not in text
    assert 'except the common operations' in s.instructions

def test_compact_discovery_can_be_switched_off(monkeypatch):
    monkeypatch.setenv('PYFIGURES_COMPACT_DISCOVERY','0')
    s,full=server(monkeypatch)
    for tool in full._tool_manager._tools.values():tool.description='documentation '*650
    result=s._tool_manager._tools['find_pyfigures_tools'].fn(query='',limit=12)
    assert result['next_offset']==len(result['tools'])
    for entry in result['tools']:assert entry['arguments_schema']['type']=='object'
