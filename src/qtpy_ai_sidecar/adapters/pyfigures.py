"""Optional HTTP adapter to the existing isolated PyFigures prototype.

No PyFigures imports, source edits, monkey patches, or file-based figure editing.
The existing bridge marshals requests onto the application's Qt thread.
"""
import json
from pathlib import Path
import uuid
import urllib.request


class PyFiguresAdapter:
    supports_preview = True

    def __init__(self, descriptor):
        self.descriptor = Path(descriptor)

    def request(self, operation, arguments=None):
        connection = json.loads(self.descriptor.read_text())
        from urllib.parse import urlsplit
        url = urlsplit(connection['url'])
        if url.hostname not in ('127.0.0.1', 'localhost', '::1'):
            raise ValueError('The PyFigures bridge must be local')
        data = json.dumps({'operation': operation, 'arguments': arguments or {},
                           'request_id': str(uuid.uuid4())}).encode()
        req = urllib.request.Request(connection['url'], data,
            headers={'Authorization': 'Bearer ' + connection['token'], 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=45) as response:
            result = json.load(response)
        if 'error' in result:
            raise RuntimeError(result['error'])
        return result['result']

    @staticmethod
    def decorate(record):
        status = record.get('status')
        controls = []
        if record.get('changed'):
            if status == 'undone':
                controls = ['redo']
            elif record.get('preview') and status in ('preview', 'interrupted'):
                controls = ['apply', 'discard']
            elif status == 'applied' or (status == 'interrupted' and not record.get('preview')):
                controls = ['undo']
        return {**record, 'controls': controls}

    def context(self):
        result = self.request('inspect')
        return {key: result.get(key) for key in ('selection', 'verified_letter_specification', 'panel_references', 'revision', 'dirty')}

    def begin(self, text, preview=False):
        return self.request('action_begin', {'text': text, 'preview': preview})

    def finish(self, interrupted=False):
        return self.decorate(self.request('action_finish', {'interrupted': interrupted}))

    def control(self, action, ident=None):
        if action not in ('undo', 'redo', 'apply', 'discard', 'recover'):
            raise ValueError('Unsupported host control')
        return self.decorate(self.request('action_' + action, {'ident': ident} if ident else {}))


def attach_to_window(window, config, descriptor):
    """Embed this package in a running PyFigures prototype main window."""
    from qtpy.QtCore import Qt
    from qtpy_ai_sidecar import create_dock
    from qtpy_ai_sidecar.branding import application_icon
    dock = create_dock(window, config, PyFiguresAdapter(descriptor))
    dock.setWindowIcon(application_icon())
    dock.setMinimumWidth(420)
    dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
    window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
    dock.setFloating(False)
    window.local_chat_dock = dock
    window.resize(max(window.width(), 1400), max(window.height(), 850))
    window.resizeDocks([dock], [480], Qt.Orientation.Horizontal)
    return dock
