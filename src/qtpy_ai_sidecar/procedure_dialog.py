"""The chat panel's Procedures menu: save this chat as a procedure, run one, or step
through a chat / procedure one call at a time (qtpy_ai_sidecar.procedures), through the
application's MCP servers, without the model."""
from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

from qtpy.QtCore import Qt
from qtpy.QtGui import QColor
from qtpy.QtWidgets import (QApplication, QCheckBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                            QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
                            QVBoxLayout, QWidget)

from . import procedures as P

_GREY, _RED, _GREEN = QColor(140, 140, 140), QColor(200, 40, 40), QColor(30, 140, 60)


class HubSession:
    """The application's MCP servers, opened once on a thread of their own and kept open
    while steps are run (opening them can start a server process)."""

    def __init__(self, servers, hub_factory=None):
        from .mcp_client import MCPHub
        self.servers, self.factory = servers, hub_factory or MCPHub
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()
        self.hub, self.error, self._closing = None, None, None
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        asyncio.set_event_loop(self.loop)
        self._closing = asyncio.Event()

        async def main():
            try:
                async with self.factory(self.servers) as hub:
                    self.hub = hub
                    self.ready.set()
                    await self._closing.wait()
            except BaseException as exc:
                self.error = exc
                self.ready.set()
        self.loop.run_until_complete(main())

    def call(self, coroutine_fn, timeout=600):
        """coroutine_fn(hub) run on the session's loop; its result, keeping Qt responsive."""
        self.ready.wait(60)
        if self.error is not None or self.hub is None:
            raise RuntimeError(f'cannot reach the application: {self.error or "timed out"}')
        future = asyncio.run_coroutine_threadsafe(coroutine_fn(self.hub), self.loop)
        app = QApplication.instance()
        while not future.done():
            if app is not None:
                app.processEvents()
            threading.Event().wait(0.02)
        return future.result(timeout)

    def close(self):
        if self._closing is not None and self.loop.is_running():
            self.loop.call_soon_threadsafe(self._closing.set)
        self.thread.join(10)


def current_document(adapter):
    """(folder, name) of the application's open document, when its state gives one."""
    try:
        doc = (adapter.context() or {}).get('document') or {}
    except Exception:
        return None, None
    return doc.get('folder'), doc.get('name')


class ProcedureDialog(QDialog):
    COLUMNS = ('#', 'Request', 'Call', 'Then', 'Now')

    def __init__(self, dock, source, parent=None):
        super().__init__(parent or dock)
        self.dock, self.engine = dock, dock.engine
        self.adapter = self.engine.adapter
        self.setWindowTitle('Step through: ' + Path(str(source)).name)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.resize(980, 600)
        self.session, self.now, self.all_steps, self.steps = None, {}, [], []
        self.source = str(source)
        self.show_all = QCheckBox('Show reads and failed calls', self)
        self.show_all.toggled.connect(lambda _c: self.fill())
        self.table = QTableWidget(0, len(self.COLUMNS), self)
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)   # every column resizable
        header.setStretchLastSection(True)
        for col, width in enumerate((36, 200, 320, 50, 50)):
            self.table.setColumnWidth(col, width)
        self.table.itemSelectionChanged.connect(self.show_step)
        side = QWidget(self)
        s = QVBoxLayout(side)
        s.setContentsMargins(0, 0, 0, 0)
        s.addWidget(QLabel('Arguments (edit them, then Run this step):', side))
        self.arguments = QPlainTextEdit(side)
        s.addWidget(self.arguments, 1)
        s.addWidget(QLabel('Result in the chat:', side))
        self.then = QPlainTextEdit(side)
        self.then.setReadOnly(True)
        s.addWidget(self.then, 1)
        s.addWidget(QLabel('Result now:', side))
        self.result = QPlainTextEdit(side)
        self.result.setReadOnly(True)
        s.addWidget(self.result, 1)
        split = QSplitter(Qt.Orientation.Horizontal, self)
        split.addWidget(self.table)
        split.addWidget(side)
        split.setSizes([620, 360])
        buttons = QHBoxLayout()
        for text, slot in (('Run this step ▶', self.run_selected), ('Run up to here', self.run_to_selected),
                           ('Run all', self.run_all), ('Save as procedure…', self.save_as)):
            b = QPushButton(text, self)
            b.clicked.connect(lambda _c=False, f=slot: f())
            buttons.addWidget(b)
        self.status = QLabel('', self)
        layout = QVBoxLayout(self)
        layout.addWidget(self.show_all)
        layout.addWidget(split, 1)
        layout.addLayout(buttons)
        layout.addWidget(self.status)
        self.load(self.source)

    def load(self, path):
        if path.lower().endswith('.json'):
            _app, self.all_steps = P.load(path)
            self.show_all.setEnabled(False)
        else:
            self.all_steps = P.load_steps(path, self.adapter)
        self.fill()

    def fill(self):
        procedure = self.source.lower().endswith('.json')
        self.steps = self.all_steps if (procedure or self.show_all.isChecked()) else P.kept_steps(self.all_steps)
        self.table.setRowCount(len(self.steps))
        for row, step in enumerate(self.steps):
            note = '' if step.role == 'edit' else f' ({step.role})'
            note += ' (undone later)' if step.turn_undone else ''
            cells = (str(row + 1), step.request, P.describe(self.adapter, step) + note,
                     '' if procedure else ('failed' if step.recorded_error else 'ok'), '')
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                if step.role != 'edit' or step.turn_undone:
                    item.setForeground(_GREY)
                if col == 3 and text:
                    item.setForeground(_RED if step.recorded_error else _GREEN)
                self.table.setItem(row, col, item)
            self._mark(row)
        self.status.setText(f'{len(self.steps)} step(s) of {len(self.all_steps)}. Each runs on the '
                            'application as it is now, without the model.')
        if self.steps:
            self.table.selectRow(0)

    def _mark(self, row):
        state = self.now.get(id(self.steps[row]))
        item = self.table.item(row, 4)
        item.setText('' if state is None else ('ok' if state[0] else 'failed'))
        if state is not None:
            item.setForeground(_GREEN if state[0] else _RED)
            item.setToolTip(state[1][:500])

    def current_row(self):
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else None

    def show_step(self):
        row = self.current_row()
        if row is None:
            return
        step = self.steps[row]
        self.arguments.setPlainText(json.dumps(step.arguments, indent=2, ensure_ascii=False))
        self.then.setPlainText(step.recorded_result)
        state = self.now.get(id(step))
        self.result.setPlainText(state[1] if state else '')

    def run_step(self, row, edited=False):
        step = self.steps[row]
        try:
            if edited:
                step.arguments = json.loads(self.arguments.toPlainText() or '{}')
            if self.session is None:
                self.session = HubSession(self.engine.config.servers, self.engine.hub_factory)
                self.document = current_document(self.adapter)
            text = self.session.call(lambda hub: P.run_step(hub, step, self.document))
            self.now[id(step)] = (True, text)
        except Exception as exc:
            self.now[id(step)] = (False, f'{type(exc).__name__}: {exc}')
        self._mark(row)
        if self.current_row() == row:
            self.show_step()
        return self.now[id(step)][0]

    def run_selected(self):
        row = self.current_row()
        if row is not None:
            self.run_step(row, edited=True)
            if row + 1 < len(self.steps):
                self.table.selectRow(row + 1)

    def run_to_selected(self):
        row = self.current_row()
        self._run_range(0 if row is None else row)

    def run_all(self):
        self._run_range(len(self.steps) - 1)

    def _run_range(self, last):
        done = failed = 0
        for row in range(last + 1):
            if id(self.steps[row]) in self.now:
                continue
            if self.run_step(row):
                done += 1
            else:
                failed += 1
        self.status.setText(f'{done} step(s) run' + (f', {failed} failed (see Now)' if failed else '') + '.')

    def save_as(self, path=None):
        procedure = self.source.lower().endswith('.json')
        steps = self.all_steps if procedure else P.kept_steps(self.all_steps)
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, 'Save as procedure', '', 'Procedure (*.json)')
            if not path:
                return None
        P.save(steps, path, self.engine.config.application, None if procedure else self.source)
        self.status.setText(f'{len(steps)} step(s) saved to {path}.')
        return path

    def closeEvent(self, event):
        if self.session is not None:
            self.session.close()
            self.session = None
        super().closeEvent(event)


# -- a recorded chat replayed in the chat panel, turn by turn --------------------------------
class ChatReplay:
    """Plays a recorded chat back in the chat panel: each turn shows the request, runs
    the edits the model made then (through the application's MCP servers; reads, failed
    calls and replies undone with their Undo button are not run), lists every call with
    what it gave then and now, and shows the model's recorded answer. For seeing again
    how a chat went, on the application as it is now, without the model."""

    def __init__(self, dock, path, apply=True):
        from qtpy.QtWidgets import QFrame
        self.dock, self.path = dock, str(path)
        self.turns = P.load_turns(self.path, dock.engine.adapter)
        self.index, self.session, self.document = 0, None, (None, None)
        self.bar = QFrame(dock.widget())
        self.bar.setObjectName('replayBar')
        row = QHBoxLayout(self.bar)
        row.setContentsMargins(6, 4, 6, 4)
        self.label = QLabel('', self.bar)
        row.addWidget(self.label, 1)
        self.apply = QCheckBox('Apply the edits', self.bar)
        self.apply.setChecked(apply)
        self.apply.setToolTip('Run the edits of each turn on the application (untick to only read the chat)')
        row.addWidget(self.apply)
        self.next_button = QPushButton('Next turn ▶', self.bar)
        self.next_button.clicked.connect(lambda _c=False: self.next())
        # green, the bar's main button: users should not miss it (user 2026-11-13)
        self.next_button.setStyleSheet(
            'QPushButton { background:#2e7d32; color:white; font-weight:600; border-radius:4px; padding:4px 10px; }'
            'QPushButton:hover { background:#388e3c; }'
            'QPushButton:disabled { background:#a5c8a7; color:#f1f1f1; }')
        row.addWidget(self.next_button)
        self.all_button = QPushButton('Play all', self.bar)
        self.all_button.clicked.connect(lambda _c=False: self.play_all())
        row.addWidget(self.all_button)
        stop = QPushButton('End replay', self.bar)
        stop.clicked.connect(lambda _c=False: self.close())
        row.addWidget(stop)
        # just above the message box, where the eye is (it was below it, user 2026-11-13)
        root = dock.widget().layout()
        composer = getattr(dock, 'composer_frame', None)
        at = root.indexOf(composer) if composer is not None else -1
        if at >= 0:
            root.insertWidget(at, self.bar)
        else:
            root.addWidget(self.bar)
        dock.add_message('assistant', f'**Replay of {Path(self.path).name}**: {len(self.turns)} request(s). '
                                      'Each turn shows what you asked, runs the edits made then on the '
                                      'application as it is now (with *Apply the edits*), and shows the '
                                      'model\'s answer then. The model is not called.')
        self.update_label()

    def update_label(self):
        done = self.index >= len(self.turns)
        self.label.setText('Replay finished' if done else f'Replay · turn {self.index + 1} of {len(self.turns)}')
        self.next_button.setEnabled(not done)
        self.all_button.setEnabled(not done)

    def _run(self, step):
        if self.session is None:
            self.session = HubSession(self.dock.engine.config.servers, self.dock.engine.hub_factory)
            self.document = current_document(self.dock.engine.adapter)
        return self.session.call(lambda hub: P.run_step(hub, step, self.document))

    def next(self):
        if self.index >= len(self.turns):
            return False
        turn = self.turns[self.index]
        self.index += 1
        self.dock.add_message('user', turn.request)
        lines = []
        for kind, item in turn.items:
            if kind == 'assistant':
                if lines:
                    self.dock.add_message('assistant', '\n'.join(lines))
                    lines = []
                self.dock.add_message('assistant', item)
            elif kind == 'error':
                lines.append(f'- ⚠ then: {item[:300]}')
            else:
                lines.append(self._call_line(item, turn))
        if lines:
            self.dock.add_message('assistant', '\n'.join(lines))
        if turn.undone:
            self.dock.add_message('assistant', '*(This reply was undone in the chat: its edits were not replayed.)*')
        self.update_label()
        return True

    def _call_line(self, step, turn):
        text = '`' + P.describe(self.dock.engine.adapter, step)[:160].replace('`', "'") + '`'
        then = 'failed' if step.recorded_error else 'ok'
        runs = (self.apply.isChecked() and step.role in ('edit', 'undo', 'redo')
                and not step.recorded_error and not turn.undone)
        if not runs:
            why = step.role if step.role != 'edit' else ('failed then' if step.recorded_error else
                                                         'undone' if turn.undone else 'not applied')
            return f'- {text}: then {then} · not run ({why})'
        try:
            self._run(step)
            now = 'ok'
        except Exception as exc:
            now = f'**failed**: {str(exc)[:200]}'
        return f'- {text}: then {then} · now {now}'

    def play_all(self):
        while self.next():
            pass

    def close(self):
        if self.session is not None:
            self.session.close()
            self.session = None
        self.bar.hide()
        self.bar.deleteLater()
        if getattr(self.dock, 'chat_replay', None) is self:
            self.dock.chat_replay = None


def replay_chat(dock, path=None, apply=True):
    """The chat panel's Procedures > Replay a chat…: a recorded chat, turn by turn."""
    if path is None:
        path, _ = QFileDialog.getOpenFileName(dock, 'Replay a chat', str(Path(dock.engine.journal.path).parent),
                                              'Chat logs (*.jsonl *.zip)')
        if not path:
            return None
    previous = getattr(dock, 'chat_replay', None)
    if previous is not None:
        previous.close()
    dock.chat_replay = ChatReplay(dock, path, apply)
    return dock.chat_replay


# -- the chat panel's Procedures menu -------------------------------------------------------
def save_this_chat(dock, path=None):
    """The current chat's edits as a procedure, next to the document by default."""
    journal = dock.engine.journal.path
    if not Path(journal).exists():
        QMessageBox.information(dock, 'Save as procedure', 'Nothing was asked in this chat yet.')
        return None
    steps = P.kept_steps(P.load_steps(journal, dock.engine.adapter))
    if not steps:
        QMessageBox.information(dock, 'Save as procedure', 'This chat changed nothing: no procedure to save.')
        return None
    if path is None:
        folder, name = P.document_of(journal)
        start = str(Path(folder) / f'{name}_procedure.json') if folder and name else 'procedure.json'
        path, _ = QFileDialog.getSaveFileName(dock, f'Save the {len(steps)} step(s) of this chat',
                                              start, 'Procedure (*.json)')
        if not path:
            return None
    P.save(steps, path, dock.engine.config.application, journal)
    dock.emit('assistant', f'Saved this chat\'s {len(steps)} step(s) as a procedure: **{path}**. '
                           'Run it from the Procedures menu (or drop it on the application, when it accepts it).')
    return path


def run_procedure(dock, path=None, stop_on_error=True):
    """Every step of a procedure on the application now. Returns (done, total, failed)."""
    if path is None:
        path, _ = QFileDialog.getOpenFileName(dock, 'Run a procedure', '', 'Procedure (*.json)')
        if not path:
            return None
    _application, steps = P.load(path)
    session = HubSession(dock.engine.config.servers, dock.engine.hub_factory)
    document = current_document(dock.engine.adapter)
    done, failed = 0, []
    try:
        for number, step in enumerate(steps, 1):
            try:
                session.call(lambda hub, s=step: P.run_step(hub, s, document))
                done += 1
            except Exception as exc:
                failed.append((number, f'{step.call}: {exc}'))
                if stop_on_error:
                    break
    finally:
        session.close()
    text = f'Procedure **{Path(path).name}**: {done} of {len(steps)} step(s) done.'
    if failed:
        text += f' Stopped at step {failed[0][0]}: {failed[0][1][:300]}'
    dock.emit('assistant', text)
    return done, len(steps), failed


def step_through(dock, path=None):
    if path is None:
        path, _ = QFileDialog.getOpenFileName(dock, 'Step through a chat or procedure',
                                              str(Path(dock.engine.journal.path).parent),
                                              'Chats and procedures (*.jsonl *.zip *.json)')
        if not path:
            return None
    dialog = ProcedureDialog(dock, path)
    dialog.show()
    return dialog
