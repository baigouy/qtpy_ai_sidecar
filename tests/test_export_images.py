"""Exported conversations carry the pictures the chat showed (canvas snapshots),
the before/after previews and a screenshot of the window: key for debugging."""
import asyncio
import base64
import json
import zipfile

from qtpy_ai_sidecar.config import Config
from qtpy_ai_sidecar.engine import Engine
from qtpy_ai_sidecar.journal import Journal

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==')


def test_snapshots_shown_in_the_chat_are_in_the_export(tmp_path):
    journal = Journal(tmp_path)
    journal.record('user', 'Make the letters red')
    saved = journal.record_image(base64.b64encode(PNG).decode(), 'image/png', 'preview_figure')
    assert saved.read_bytes() == PNG
    journal.record_image(base64.b64encode(PNG).decode(), 'image/jpeg', 'preview_panel')
    journal.record_image('not base64 !!', 'image/png', 'broken')          # logged, never fatal
    before, after = tmp_path / 'before.pyf', tmp_path / 'after.pyf'
    before.with_suffix('.png').write_bytes(PNG)
    after.with_suffix('.png').write_bytes(PNG)
    journal.record('action', {'status': 'preview', 'before': str(before), 'after': str(after)})
    out = tmp_path / 'debug.zip'
    journal.export(out, screenshots={'window.png': PNG})
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        md = z.read('conversation.md').decode()
        events = [json.loads(line) for line in z.read('events.jsonl').decode().splitlines()]
        assert {'images/001.png', 'images/002.jpg', 'screenshots/window.png'} <= names
        assert z.read('images/001.png') == PNG
        assert '![preview_figure](images/001.png)' in md and '![preview_panel](images/002.jpg)' in md
        assert '![window.png](screenshots/window.png)' in md
        previews = sorted(n for n in names if n.startswith('images/preview_'))
        assert previews == ['images/preview_003_before.png', 'images/preview_004_after.png']
        assert '![before](' in md and '![after](' in md
        assert any(e['kind'] == 'image' and 'undecodable' in str(e['value'].get('error')) for e in events)
        assert 'images/' in z.read('README.txt').decode()


def test_export_without_pictures_still_works(tmp_path):
    journal = Journal(tmp_path)
    journal.record('user', 'Hello')
    journal.export(tmp_path / 'debug.zip')
    with zipfile.ZipFile(tmp_path / 'debug.zip') as z:
        assert not [n for n in z.namelist() if n.startswith(('images/', 'screenshots/'))]


def test_tool_images_reach_the_journal_and_the_chat(tmp_path):
    engine = Engine(Config(state_dir=str(tmp_path)))
    shown = []
    forward = engine._keeping_images(lambda kind, value: shown.append(kind), 'tool-7')
    forward('image', {'data': base64.b64encode(PNG).decode(), 'mime': 'image/png'})
    forward('status', 'running')
    assert shown == ['image', 'status']
    assert (engine.journal.images / '001.png').read_bytes() == PNG
    assert '"source": "tool-7"' in engine.journal.path.read_text(encoding='utf-8')


def test_real_mcp_image_lands_in_the_export(tmp_path):
    # the MCP client emits tool images; the engine wrapper must keep them
    from qtpy_ai_sidecar.mcp_client import MCPHub

    class Block:
        type = 'image'
        data = base64.b64encode(PNG).decode()
        mimeType = 'image/png'

    class Result:
        content = [Block()]
        isError = False
        structuredContent = None

    class Session:
        async def call_tool(self, name, arguments):
            return Result()

    class Tool:
        name = 'preview_figure'
        inputSchema = {}

    engine = Engine(Config(state_dir=str(tmp_path)))
    hub = MCPHub.__new__(MCPHub)
    hub.tools = {'t1': ('pyfigures', Session(), Tool())}
    asyncio.run(hub.execute('t1', {}, engine._keeping_images(lambda *a: None, 't1')))
    engine.journal.export(tmp_path / 'debug.zip')
    with zipfile.ZipFile(tmp_path / 'debug.zip') as z:
        assert z.read('images/001.png') == PNG


def test_dock_export_adds_a_window_screenshot(tmp_path):
    from qtpy.QtWidgets import QApplication
    from qtpy_ai_sidecar.widgets import AssistantDock
    app = QApplication.instance() or QApplication([])
    dock = AssistantDock(Config(application='Demo', state_dir=str(tmp_path)))
    dock.resize(400, 500)
    dock.show()
    app.processEvents()
    shots = dock.screenshots()
    assert shots['window.png'][:8] == b'\x89PNG\r\n\x1a\n'
    dock.engine.journal.record('user', 'Test')
    dock.engine.journal.export(tmp_path / 'debug.zip', screenshots=shots)
    with zipfile.ZipFile(tmp_path / 'debug.zip') as z:
        assert 'screenshots/window.png' in z.namelist()
    dock.shutdown()
    dock.close()
