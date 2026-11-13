"""Chats as procedures, in the sidecar so every application gets them (user, 2026-11-13:
"shouldn't this procedure save and export and import rather be part of the AI side car
itself? ... if this makes it reusable for other tools then yes"). A fake MCP hub stands
for the application: no model, no network."""
import json
import zipfile
from types import SimpleNamespace

import pytest

from qtpy_ai_sidecar import procedures as P
from qtpy_ai_sidecar.adapters.pyfigures import PyFiguresAdapter


def _ev(kind, value):
    return json.dumps({'time': '2026-11-13T13:15:34+00:00', 'kind': kind, 'value': value})


def _use(op, arguments, batch=None):
    value = {'tool_name': op, 'arguments': arguments, **({'batch': batch} if batch else {})}
    return _ev('tool_call', {'name': 'use_pyfigures_tool', 'arguments': value})


OK = _ev('tool_result', {'is_error': False, 'content': 'done'})
FAILED = _ev('tool_result', {'is_error': True, 'content': 'Unknown argument(s): colour'})


def _chat(tmp_path):
    both = [{'panel_ref': 'a'}, {'panel_ref': 'b'}]
    lines = [
        _ev('user', 'rotate all by 25'),
        _ev('host_context', {'document': {'folder': 'C:/figs', 'name': 'wing'}}),
        _ev('tool_call', {'name': 'find_pyfigures_tools', 'arguments': {'query': 'rotate'}}), OK,
        _use('transform_image', {'rotation': 25}, both), OK,
        _use('preview_panel', {'panel_ref': 'a'}), OK,
        _ev('user', 'black backgrounds'),
        _use('set_image_property', {'property_name': 'fill_color', 'colour': '0'}, both), FAILED,
        _use('set_image_property', {'property_name': 'fill_color', 'value': '0'}, both), OK,
        _ev('user', 'red letters'),
        _use('edit_panel_letters', {'color': 'red', 'scope': 'all'}), OK,
        _ev('action', {'request': 'red letters', 'status': 'undone'}),
        _ev('user', 'crop a'),
        _use('transform_image', {'panel_ref': 'a', 'crop_left': 10}), OK,
        _ev('user', 'undo that'),
        _ev('tool_call', {'name': 'undo_redo', 'arguments': {'action': 'undo'}}), OK,
        _ev('user', 'open the editor'),
        _use('open_annotation_editor', {'panel_ref': 'a'}), OK,
        _ev('user', 'save it as a ppt'),
        _use('export_pptx', {'out_path': 'C:/figs/wing.pptx'}), OK,
    ]
    path = tmp_path / 'chat.jsonl'
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return path


def test_the_edits_that_stayed(tmp_path):
    adapter = PyFiguresAdapter('unused')
    steps = P.load_steps(_chat(tmp_path), adapter)
    assert [s.role for s in steps] == ['read', 'edit', 'read', 'edit', 'edit', 'edit', 'edit', 'undo', 'skip', 'edit']
    kept = P.kept_steps(steps)
    assert [P.describe(adapter, s) for s in kept] == [
        'transform_image {"rotation": 25} × 2', 'set_image_property {"property_name": "fill_color", "value": "0"} × 2',
        'export_pptx {"out_path": "C:/figs/wing.pptx"}']
    # without an adapter: only the names say what reads
    plain = P.kept_steps(P.load_steps(_chat(tmp_path)))
    assert len(plain) > len(kept)


def test_a_debug_zip_and_a_saved_procedure(tmp_path):
    chat = _chat(tmp_path)
    z = tmp_path / 'sidecar-debug.zip'
    with zipfile.ZipFile(z, 'w') as out:
        out.writestr('events.jsonl', chat.read_text(encoding='utf-8'))
    adapter = PyFiguresAdapter('unused')
    kept = P.kept_steps(P.load_steps(z, adapter))
    path = P.save(kept, tmp_path / 'p.json', 'PyFigures', source=chat)
    data = json.loads(open(path, encoding='utf-8').read())
    assert data['procedure'] == 1 and data['application'] == 'PyFigures' and len(data['steps']) == 3
    assert data['steps'][2]['arguments'] == {'tool_name': 'export_pptx', 'arguments': {'out_path': '{folder}/{name}.pptx'}}
    app, again = P.load(path)
    assert app == 'PyFigures' and again[0].call == 'use_pyfigures_tool'
    assert P.filled(again[2].arguments, 'D:/x', 'kidney')['arguments']['out_path'] == 'D:/x/kidney.pptx'
    (tmp_path / 'bad.json').write_text('{"steps": [{"request": "x"}]}', encoding='utf-8')
    with pytest.raises(ValueError, match='names no MCP call'):
        P.load(tmp_path / 'bad.json')


class Hub:
    """An application with two operations; 'boom' fails."""
    def __init__(self, *args):
        self.calls = []
        tool = lambda name: SimpleNamespace(name=name)
        self.tools = {'t1': ('app', None, tool('use_pyfigures_tool')), 't2': ('app', None, tool('boom'))}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, ident, arguments, emit):
        self.calls.append((ident, arguments))
        if ident == 't2':
            return {'is_error': True, 'content': 'it broke'}
        return {'is_error': False, 'content': 'ok ' + json.dumps(arguments)}


def test_steps_run_through_the_applications_mcp_servers(tmp_path):
    import asyncio
    hub = Hub()
    step = P.Step('save', 1, 'use_pyfigures_tool', {'tool_name': 'export_pptx', 'arguments': {'out_path': '{folder}/{name}.pptx'}})
    text = asyncio.run(P.run_step(hub, step, ('D:/x', 'kidney')))
    assert 'D:/x/kidney.pptx' in text and hub.calls[0][1]['arguments']['out_path'] == 'D:/x/kidney.pptx'
    with pytest.raises(RuntimeError, match='it broke'):
        asyncio.run(P.run_step(hub, P.Step('', 1, 'boom', {})))
    with pytest.raises(ValueError, match='no connected application'):
        asyncio.run(P.run_step(hub, P.Step('', 1, 'nope', {})))


def test_a_chat_is_replayed_in_the_chat_panel_turn_by_turn(tmp_path):
    """'I dropped it but I don't see the stuff entered in the chat nor the model answer'
    (user, 2026-11-13): the replay shows each request, runs its edits, lists the calls
    (then / now) and the model's answer then."""
    from qtpy.QtWidgets import QApplication
    from qtpy_ai_sidecar.config import Config
    from qtpy_ai_sidecar.widgets import AssistantDock
    app = QApplication.instance() or QApplication([])
    chat = tmp_path / 'talk.jsonl'
    lines = _chat(tmp_path).read_text(encoding='utf-8').splitlines()
    lines.insert(5, _ev('assistant', 'Done: all panels rotated 25°.'))      # after the first turn's calls
    chat.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    turns = P.load_turns(chat, PyFiguresAdapter('unused'))
    assert [t.request for t in turns][:2] == ['rotate all by 25', 'black backgrounds']
    assert [k for k, _ in turns[0].items] == ['call', 'call', 'assistant', 'call'] and turns[2].undone
    hub = Hub()
    dock = AssistantDock(Config(application='Demo', state_dir=str(tmp_path)))
    dock.engine.hub_factory = lambda servers: hub
    dock.engine.adapter = PyFiguresAdapter('unused')
    dock.engine.adapter.context = lambda: {}
    shown = []
    real = dock.add_message
    dock.add_message = lambda role, text: (shown.append((role, text)), real(role, text))[1]
    replay = dock.procedure_action('replay', str(chat))
    try:
        assert replay.next()
        roles = [r for r, _ in shown[1:]]
        assert roles[0] == 'user' and shown[1][1] == 'rotate all by 25'
        assert any('Done: all panels rotated' in t for _, t in shown)
        assert any('transform_image' in t and 'now ok' in t for _, t in shown)
        assert any('find_pyfigures_tools' in t and 'not run (read)' in t for _, t in shown)
        assert len(hub.calls) == 1                                     # only the edit ran
        replay.play_all()
        assert replay.index == len(turns) and replay.label.text() == 'Replay finished'
        assert any('undone in the chat' in t for _, t in shown)
        # the red letters were undone with the Undo button, the crop by the chat: not run
        assert not any(c[1].get('tool_name') == 'edit_panel_letters' for c in hub.calls)
    finally:
        replay.close()
    app.processEvents()


def test_the_chat_panels_procedures_menu(tmp_path, monkeypatch):
    """Save this chat → run it → step through it, from the chat panel, any application."""
    from qtpy.QtWidgets import QApplication
    from qtpy_ai_sidecar.config import Config
    from qtpy_ai_sidecar.widgets import AssistantDock
    app = QApplication.instance() or QApplication([])
    hub = Hub()
    dock = AssistantDock(Config(application='Demo', state_dir=str(tmp_path)))
    dock.engine.hub_factory = lambda servers: hub
    dock.engine.adapter = PyFiguresAdapter('unused')
    dock.engine.adapter.context = lambda: {'document': {'folder': 'D:/x', 'name': 'kidney'}}
    journal = dock.engine.journal.path
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(_chat(tmp_path).read_text(encoding='utf-8'), encoding='utf-8')
    saved = dock.procedure_action('save', str(tmp_path / 'mine.json'))
    assert len(P.load(saved)[1]) == 3
    done, total, failed = dock.procedure_action('run', saved)
    assert (done, total, failed) == (3, 3, []) and len(hub.calls) == 3
    assert hub.calls[2][1]['arguments']['out_path'] == 'D:/x/kidney.pptx'     # the open document's name
    dialog = dock.procedure_action('step', str(journal))
    try:
        assert dialog.table.rowCount() == 3
        dialog.table.selectRow(0)
        dialog.run_selected()
        assert dialog.table.item(0, 4).text() == 'ok' and dialog.current_row() == 1
        dialog.show_all.setChecked(True)
        assert dialog.table.rowCount() == 10
    finally:
        dialog.close()
    app.processEvents()
