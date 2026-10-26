"""Contracts are tested without importing the live GUI/model server."""
import ast
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from qtpy_ai_sidecar.adapters.pyfigures import PyFiguresAdapter

prototype=Path(__file__).resolve().parents[2]/'pyfigures_pkg/chatGPT_validation/live_mcp_gui'
if not (prototype/'categorized_mcp.py').exists():
    pytest.skip('Optional PyFigures prototype is not installed',allow_module_level=True)

def swap_doc():
    tree=ast.parse((prototype/'live_mcp.py').read_text(encoding='utf-8'))
    return ast.get_docstring(next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='swap_live_panels'))

def test_swap_description_defaults_to_images_and_stops_on_unresolved_refs():
    doc=swap_doc()
    assert doc.startswith('Swap IMAGE PANELS')
    assert 'target=images is the default' in doc
    assert 'Letter TEXT swaps' in doc and 'explicit' in doc
    assert 'STOP and ask' in doc
    assert 'never substitute' in doc and 'retry with other references' in doc

def test_adapter_gives_same_swap_contract():
    text=PyFiguresAdapter('unused').context_instructions({})
    assert 'Swap IMAGE PANELS by default' in text
    assert 'explicit swap-the-letters/labels' in text
    assert 'STOP and ask' in text and 'never substitute an existing panel' in text

@pytest.fixture
def font_server(monkeypatch):
    monkeypatch.syspath_prepend(str(prototype))
    spec=importlib.util.spec_from_file_location('swap_fonts_categories',prototype/'categorized_mcp.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setitem(sys.modules,'original_registry',SimpleNamespace(registry=lambda:{'list_fonts':None}))
    monkeypatch.setitem(sys.modules,'source_help',SimpleNamespace(explain_feature=lambda topic:None))
    monkeypatch.setitem(sys.modules,'manual_help',SimpleNamespace(explain=lambda topic:{'status':'not_found'}))
    full=FastMCP('font contracts')
    calls=[]
    @full.tool(annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False))
    def list_fonts(query:str|None=None)->dict:
        """Read-only fonts typeface inventory: Helvetica, Arial, available and installed."""
        calls.append(query)
        return {'count':1,'installed_families':['Arial']}
    server=module.build_server(full,lambda *a,**kw:{})
    return server,calls,module

@pytest.mark.parametrize('query',['font','fonts','helvetica','typeface','available','is Arial installed?'])
def test_font_discovery_is_lettering_readonly_and_does_not_execute(font_server,query):
    server,calls,module=font_server
    found=server._tool_manager._tools['find_pyfigures_tools'].fn(query=query,category='lettering')
    item=next(t for t in found['tools'] if t['name']=='list_fonts')
    assert item['category']=='lettering'
    assert 'query' in item['arguments_schema']['properties']
    assert calls==[]
    assert 'font_check' in server.instructions

def test_registry_advertises_readonly_font_tool_without_changing_native_registration():
    tree=ast.parse((prototype/'original_registry.py').read_text(encoding='utf-8'))
    calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='add_tool']
    annotation=next(k.value for k in calls[0].keywords if k.arg=='annotations')
    assert isinstance(annotation,ast.IfExp)
    assert ast.unparse(annotation.test)=="name == 'list_fonts'"
    values={k.arg:ast.literal_eval(k.value) for k in annotation.body.keywords}
    assert values=={'readOnlyHint':True,'destructiveHint':False}
    assert 'font_check' in PyFiguresAdapter('unused').context_instructions({})


def test_named_panel_precedes_positional_description():
    assert 'uniquely named panel wins' in swap_doc()
    assert 'Never edit then undo' in swap_doc()
    text=PyFiguresAdapter('unused').context_instructions({})
    assert 'uniquely named panel wins' in text
    assert 'conflicts with its description' not in text

def test_categorized_font_wrapper_keeps_query_and_bounds_inventory(font_server):
    import asyncio
    server,calls,module=font_server
    dispatch=server._tool_manager._tools['use_pyfigures_tool'].fn
    query=asyncio.run(dispatch('list_fonts',{'query':'Arial'}))
    assert query=={'count':1,'installed_families':['Arial']}
    result=asyncio.run(dispatch('list_fonts',{}))
    assert result['total_count']==1 and result['returned_count']==1
    assert calls==['Arial',None]
    assert 'list_fonts' not in server._tool_manager._tools

def test_only_one_short_font_line_remains_in_system_text(font_server):
    server,_,_=font_server
    assert server.instructions.count('Is a font available?')==1
    text=PyFiguresAdapter('unused').context_instructions({})
    assert text.count('Is a font available?')==1
    assert 'Before changing a font family' not in server.instructions+text
