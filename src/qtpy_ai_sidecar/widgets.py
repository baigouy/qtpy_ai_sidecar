"""QtPy widget layer. All GUI updates are delivered by queued Qt signals."""
import asyncio
import base64
import html
import json
import re
import threading
import time
import sys
from qtpy.QtCore import Qt, Signal, QTimer
from qtpy.QtGui import QImage, QPixmap, QFont
from qtpy.QtWidgets import (QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QFrame, QLabel, QTextBrowser, QPlainTextEdit, QPushButton, QProgressBar,
    QFileDialog, QCheckBox, QSizePolicy, QDialog, QFormLayout, QSpinBox, QComboBox, QDialogButtonBox)
import qtawesome as qta
from .engine import Engine
from .adapters import NullAdapter


class Composer(QPlainTextEdit):
    submitted = Signal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.submitted.emit()
            event.accept()
        else:
            super().keyPressEvent(event)


def choices(text):
    """Selectable only for a current explicit question, never completion summaries."""
    if '?' not in text:
        return []
    lines = text.splitlines()
    result = []
    for line in lines:
        match = re.match(r'^\s*(?:\d+[.)]|[-*•])\s+(.+?)\s*$', line)
        if match:
            result.append(match.group(1))
    return result if 2 <= len(result) <= 8 else []


class MessageBrowser(QTextBrowser):
    """Fit to actual wrapped text; the outer conversation owns scrolling."""
    def __init__(self):
        super().__init__()
        self._fitting = False
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.document().documentLayout().documentSizeChanged.connect(self.fit_text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_text()

    def fit_text(self, *args):
        if self._fitting:
            return
        self._fitting = True
        try:
            self.document().setTextWidth(max(60, self.viewport().width()))
            height = max(26, int(self.document().size().height() + 2 * self.frameWidth() + 2))
            if self.height() != height:
                self.setFixedHeight(height)
        finally:
            self._fitting = False


class AssistantDock(QDockWidget):
    message_event = Signal(str, object)
    completed = Signal()

    def __init__(self, config, adapter=None, parent=None):
        super().__init__(config.application + ' Assistant', parent)
        self.setObjectName('qtpy_ai_sidecar')
        self.engine = Engine(config, adapter)
        self.busy = False
        self.thread = None
        self.closed = False
        self.choice_buttons = []
        self.last_assistant = ''
        self.started = 0
        self.activity_text = 'Ready'
        body = QWidget()
        family = 'Segoe UI' if sys.platform == 'win32' else ('Helvetica Neue' if sys.platform == 'darwin' else 'DejaVu Sans')
        body.setFont(QFont(family, 10))
        body.setObjectName('sidecarBody')
        self.setWidget(body)
        root = QVBoxLayout(body)
        top = QHBoxLayout()
        title = QLabel(config.application + ' Assistant')
        title.setStyleSheet('font-size:18px; font-weight:600')
        top.addWidget(title, 1)
        export = QPushButton(qta.icon('fa5s.file-export'), '')
        export.setToolTip('Export this conversation for debugging')
        export.clicked.connect(self.export)
        top.addWidget(export)
        self.settings_button = QPushButton(qta.icon('fa5s.cog'), '')
        self.settings_button.setToolTip('Model performance and thinking settings')
        self.settings_button.clicked.connect(self.settings)
        top.addWidget(self.settings_button)
        self.connection_button = QPushButton(qta.icon('fa5s.plug'), '')
        self.connection_button.setToolTip('Local or API connection; secure credentials')
        self.connection_button.clicked.connect(self.connection_settings)
        top.addWidget(self.connection_button)
        self.library_button = QPushButton(qta.icon('fa5s.download'), '')
        self.library_button.setToolTip('Model library and llama.cpp updates')
        self.library_button.clicked.connect(self.library)
        top.addWidget(self.library_button)
        self.tools_button = QPushButton(qta.icon('fa5s.tools'), '')
        self.tools_button.setToolTip('Import application MCP server configuration')
        self.tools_button.clicked.connect(self.import_servers)
        top.addWidget(self.tools_button)
        root.addLayout(top)
        self.connection_label = QLabel()
        self.connection_label.setWordWrap(True)
        root.addWidget(self.connection_label)
        self.update_connection_label()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        content = QWidget()
        self.messages = QVBoxLayout(content)
        self.messages.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.messages.addStretch(1)
        self.scroll.setWidget(content)
        root.addWidget(self.scroll, 1)
        self.choice_row = QVBoxLayout()
        root.addLayout(self.choice_row)
        self.preview = QCheckBox('Preview edits before applying')
        self.preview.setVisible(bool(getattr(self.engine.adapter, 'supports_preview', False)))
        root.addWidget(self.preview)
        self.input = Composer()
        self.input.setPlaceholderText('Ask about your application…  Enter sends · Shift+Enter adds a line')
        self.input.setFixedHeight(76)
        self.input.submitted.connect(self.send)
        root.addWidget(self.input)
        controls = QHBoxLayout()
        self.compress = QPushButton(qta.icon('fa5s.compress-alt'), 'Compress')
        self.compress.clicked.connect(lambda: self.run(lambda: self.engine.compact(self.emit)))
        controls.addWidget(self.compress)
        self.inspect_ack = QPushButton('Acknowledge inspection')
        self.inspect_ack.setToolTip('After checking the application, allow a new request. Nothing is replayed.')
        self.inspect_ack.clicked.connect(self.acknowledge)
        self.inspect_ack.hide()
        controls.addWidget(self.inspect_ack)
        controls.addStretch()
        self.stop = QPushButton(qta.icon('fa5s.stop'), 'Stop')
        self.stop.clicked.connect(self.engine.cancel.set)
        self.stop.setEnabled(False)
        controls.addWidget(self.stop)
        self.send_button = QPushButton(qta.icon('fa5s.paper-plane'), 'Send')
        self.send_button.clicked.connect(self.send)
        controls.addWidget(self.send_button)
        root.addLayout(controls)
        self.status = QLabel('Ready')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setMaximumHeight(6)
        self.progress.hide()
        root.addWidget(self.progress)
        self.context = QLabel(f'Context: estimated usage shown after a request · capacity {config.context_tokens:,}')
        self.context.setWordWrap(True)
        root.addWidget(self.context)
        body.setStyleSheet('''QWidget#sidecarBody {background:#fbf7f1;color:#493c32;}
            QPlainTextEdit {background:#fffdf9;border:1px solid #d8bea9;border-radius:9px;padding:9px;}
            QPlainTextEdit:disabled {background:#e8e2da;color:#81756a;}
            QPushButton {padding:7px;border:1px solid #d8bea9;border-radius:7px;}
            QPushButton:hover {background:#f0dfcc;} QScrollArea {border:0;}
            QFrame[role="assistant"] {background:#fffdf9;border:1px solid #e2cdbb;border-radius:12px;}
            QFrame[role="user"] {background:#f3e4d4;border:1px solid #dfc8b3;border-radius:12px;}
            QTextBrowser {background:transparent;border:0;}''')
        self.message_event.connect(self.receive)
        self.completed.connect(self.finished)
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.tick)
        self.add_message('assistant', 'What would you like to do in ' + config.application + '?')

    def emit(self, kind, value):
        if not self.closed:
            self.message_event.emit(kind, value)

    def add_message(self, role, text):
        frame = QFrame()
        frame.setProperty('role', role)
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(5)
        label = QLabel(('You' if role == 'user' else self.engine.config.application + ' Assistant') + ' · ' + time.strftime('%H:%M'))
        label.setStyleSheet('color:#a17351;font-weight:600')
        label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout.addWidget(label)
        browser = MessageBrowser()
        browser.document().setDefaultFont(self.widget().font())
        browser.setOpenExternalLinks(False)
        browser.setMarkdown(text)
        QTimer.singleShot(0, browser.fit_text)
        layout.addWidget(browser)
        row = QHBoxLayout()
        row.setContentsMargins(65 if role == 'user' else 0, 3, 0 if role == 'user' else 45, 3)
        row.addWidget(frame, 0, Qt.AlignmentFlag.AlignTop)
        self.messages.insertLayout(self.messages.count() - 1, row)
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum()))
        return layout

    def clear_choices(self):
        for button in self.choice_buttons:
            self.choice_row.removeWidget(button)
            button.deleteLater()
        self.choice_buttons.clear()

    def choose(self, text):
        if self.busy:
            return
        self.input.setPlainText(text)
        self.input.setFocus()
        self.clear_choices()

    def receive(self, kind, value):
        if kind == 'assistant':
            self.clear_choices()
            self.last_assistant = value
            self.add_message('assistant', value)
        elif kind == 'action' and value:
            layout = self.add_message('assistant', 'Document action: ' + value.get('status', 'recorded'))
            for action in value.get('controls', []):
                button = QPushButton(action.capitalize() + ' this message' if action in ('undo', 'redo') else action.capitalize() + ' draft')
                button.clicked.connect(lambda checked=False, a=action, ident=value.get('id'): self.host_control(a, ident))
                layout.addWidget(button)
            if value.get('preview') and value.get('status') in ('preview', 'interrupted'):
                self.comparison(layout, value)
        elif kind == 'image':
            raw = base64.b64decode(value['data'])
            image = QImage.fromData(raw)
            if not image.isNull():
                layout = self.add_message('assistant', 'Application preview')
                label = QLabel()
                label.setPixmap(QPixmap.fromImage(image).scaledToWidth(420, Qt.TransformationMode.SmoothTransformation))
                layout.addWidget(label)
        elif kind == 'status':
            self.activity_text = str(value)
            self.tick()
        elif kind == 'generation':
            self.activity_text = f"Generating · {value['characters']:,} characters"
            self.tick()
        elif kind == 'context':
            self.context.setText(f"Context ≈ {value['estimated_tokens']:,} / {value['context_tokens']:,} tokens · output limit {value['output_tokens']:,}")
        elif kind == 'usage':
            self.context.setText('Server usage: ' + json.dumps(value))
        elif kind == 'compression':
            self.add_message('assistant', f"Compressed working context: ≈{value['estimated_before']:,} → ≈{value['estimated_after']:,} tokens. Full conversation retained in the local log.")
        elif kind == 'error':
            self.last_assistant = ''
            self.add_message('assistant', 'Could not complete: ' + str(value))

    def comparison(self, layout, record):
        from .comparison import Comparison
        before = record.get('before')
        after = record.get('after')
        if before and after:
            from pathlib import Path
            first, second = Path(before).with_suffix('.png'), Path(after).with_suffix('.png')
            if first.is_file() and second.is_file():
                layout.addWidget(Comparison(first, second))

    def host_control(self, action, ident=None):
        self.clear_choices()
        self.last_assistant = ''
        self.run(lambda: self.engine.control(action, ident, self.emit))

    def acknowledge(self):
        self.engine.acknowledge()
        self.inspect_ack.hide()
        self.status.setText('Inspection acknowledged; no operation replayed')

    def run(self, job):
        if self.busy:
            return
        self.busy = True
        self.started = time.monotonic()
        self.engine.cancel.clear()
        self.input.setEnabled(False)
        self.send_button.setEnabled(False)
        self.compress.setEnabled(False)
        self.settings_button.setEnabled(False)
        self.connection_button.setEnabled(False)
        self.library_button.setEnabled(False)
        self.tools_button.setEnabled(False)
        self.preview.setEnabled(False)
        self.stop.setEnabled(True)
        self.progress.show()
        self.timer.start()
        def work():
            try:
                asyncio.run(job())
            except BaseException as exc:
                import traceback
                from .errors import error_details
                self.engine.journal.record('error_traceback', ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
                self.engine.journal.record('error', error_details(exc))
                self.emit('error', error_details(exc))
            finally:
                if not self.closed:
                    self.completed.emit()
                if self.closed:
                    close = getattr(self.engine.backend, 'close', None)
                    if close:
                        close()
        self.thread = threading.Thread(target=work, daemon=False)
        self.thread.start()

    def finished(self):
        self.busy = False
        self.timer.stop()
        self.progress.hide()
        self.input.setEnabled(True)
        self.send_button.setEnabled(True)
        self.compress.setEnabled(True)
        self.settings_button.setEnabled(True)
        self.connection_button.setEnabled(True)
        self.library_button.setEnabled(True)
        self.tools_button.setEnabled(True)
        self.preview.setEnabled(True)
        self.stop.setEnabled(False)
        self.inspect_ack.setVisible(self.engine.uncertain)
        elapsed = time.monotonic() - self.started if self.started else 0
        self.status.setText(f'Finished · {elapsed:.1f}s')
        self.clear_choices()
        for option in choices(self.last_assistant):
            button = QPushButton(option)
            button.clicked.connect(lambda checked=False, text=option: self.choose(text))
            self.choice_row.addWidget(button)
            self.choice_buttons.append(button)

    def tick(self):
        self.status.setText(self.activity_text + (f' · {time.monotonic() - self.started:.0f}s' if self.busy else ''))

    def send(self):
        text = self.input.toPlainText().strip()
        if not text or self.busy:
            return
        self.clear_choices()
        self.last_assistant = ''
        self.input.clear()
        if text.lower() == '/compact':
            self.run(lambda: self.engine.compact(self.emit))
            return
        self.add_message('user', text)
        if re.fullmatch(r'(?:/redo|redo(?:\s+(?:it|that|this|please|sorry|again))*)[.!?]*', text, re.I) and not isinstance(self.engine.adapter, NullAdapter):
            self.engine.journal.record('user', text)
            self.host_control('redo')
            return
        preview = self.preview.isChecked()
        self.run(lambda: self.engine.turn(text, self.emit, preview))

    def settings(self):
        if self.busy:
            return
        config = self.engine.config
        dialog = QDialog(self)
        dialog.setWindowTitle('Performance and thinking')
        form = QFormLayout(dialog)
        context = QSpinBox()
        context.setRange(2048, 1048576)
        context.setSingleStep(1024)
        context.setValue(config.context_tokens)
        form.addRow('Context tokens', context)
        output = QSpinBox()
        output.setRange(512, 262144)
        output.setSingleStep(512)
        output.setValue(config.output_tokens)
        form.addRow('Maximum output tokens', output)
        mode, strength = QComboBox(), QComboBox()
        mode.addItems(['default', 'enabled', 'disabled'])
        mode.setCurrentText(config.thinking)
        strength.addItems(['default', 'low', 'medium', 'high'])
        strength.setCurrentText(config.thinking_strength)
        supported = config.thinking_backend != 'unsupported'
        mode.setEnabled(supported)
        strength.setEnabled(supported)
        form.addRow('Thinking mode', mode)
        form.addRow('Thinking strength (model dependent)', strength)
        note = QLabel('Thinking controls are unavailable for this backend.' if not supported else
            'Thinking strength is a template hint; some models ignore it. A token budget gives a firmer limit on compatible owned llama.cpp runtimes.')
        note.setWordWrap(True)
        form.addRow(note)
        budget = QSpinBox()
        budget.setRange(-1, 262144)
        budget.setSpecialValueText('Default / unrestricted')
        budget.setValue(config.thinking_budget)
        budget.setEnabled(bool(config.runtime))
        form.addRow('Thinking token budget (owned runtime)', budget)
        gpu = QSpinBox()
        gpu.setRange(0, 999)
        gpu.setValue(config.runtime.get('gpu_layers', 99))
        gpu.setEnabled(bool(config.runtime))
        form.addRow('GPU layers (0 = CPU only)', gpu)
        force_cpu = QCheckBox('Force CPU — keep the GPU free for other work')
        force_cpu.setChecked(config.runtime.get('force_cpu', False))
        force_cpu.setEnabled(bool(config.runtime))
        gpu.setEnabled(bool(config.runtime) and not force_cpu.isChecked())
        force_cpu.toggled.connect(lambda checked: gpu.setEnabled(bool(config.runtime) and not checked))
        form.addRow(force_cpu)
        threads = QSpinBox()
        threads.setRange(0, 256)
        threads.setSpecialValueText('Automatic')
        threads.setValue(config.runtime.get('threads', 0))
        threads.setEnabled(bool(config.runtime))
        form.addRow('CPU threads', threads)
        info = QLabel('Changes reload our owned model on the next request.' if config.runtime else
            'External server: context is the conversation budget only. Set actual model allocation and CPU/GPU in your model server.')
        info.setWordWrap(True)
        form.addRow(info)
        error = QLabel()
        error.setWordWrap(True)
        form.addRow(error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        form.addRow(buttons)
        buttons.rejected.connect(dialog.reject)
        def save():
            if output.value() >= context.value():
                error.setText('Output limit must be smaller than context size.')
                return
            if budget.value() > output.value():
                error.setText('Thinking budget must not exceed the total output limit.')
                return
            config.context_tokens, config.output_tokens = context.value(), output.value()
            config.thinking, config.thinking_strength = mode.currentText(), strength.currentText()
            config.thinking_budget = budget.value()
            if config.runtime:
                config.runtime.update(gpu_layers=gpu.value(), threads=threads.value(), force_cpu=force_cpu.isChecked())
                close = getattr(self.engine.backend, 'close', None)
                if close:
                    close()
            config.save_performance()
            config.save_connection()
            self.engine.context(self.emit)
            dialog.accept()
        buttons.accepted.connect(save)
        dialog.exec()

    def update_connection_label(self):
        config = self.engine.config
        self.connection_label.setText(('Local model' if config.provider == 'local' else 'Remote API · ' + config.provider)
                                      + ' · ' + config.model)

    def replace_engine(self, config):
        adapter = self.engine.adapter
        close = getattr(self.engine.backend, 'close', None)
        if close:
            close()
        self.engine = Engine(config, adapter)
        self.stop.clicked.disconnect()
        self.stop.clicked.connect(self.engine.cancel.set)
        self.last_assistant = ''
        self.clear_choices()
        self.update_connection_label()
        self.add_message('assistant', 'Connection updated. Working context starts fresh; earlier conversation remains in its local log.')

    def connection_settings(self):
        if self.busy:
            return
        from .connection import ConnectionDialog
        dialog = ConnectionDialog(self.engine.config, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.replace_engine(dialog.result_config)

    def import_servers(self):
        if self.busy:
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Import MCP configuration', '', 'JSON (*.json)')
        if path:
            try:
                self.engine.config.import_servers(path)
                self.replace_engine(self.engine.config)
            except Exception as exc:
                self.add_message('assistant', 'MCP configuration was not imported: ' + str(exc))

    def library(self):
        if self.busy:
            return
        from dataclasses import asdict
        from .config import Config
        from .library import LibraryDialog
        candidate = Config(**asdict(self.engine.config))
        dialog = LibraryDialog(candidate, self)
        dialog.exec()
        if asdict(candidate) != asdict(self.engine.config):
            self.replace_engine(candidate)

    def export(self):
        if self.busy:
            self.status.setText('Wait for the current operation before exporting')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export conversation', 'sidecar-debug.zip', 'ZIP (*.zip)')
        if path:
            try:
                self.engine.journal.export(path)
                self.status.setText('Exported ' + path)
            except Exception as exc:
                self.add_message('assistant', 'Export failed: ' + str(exc))

    def shutdown(self):
        self.closed = True
        self.engine.cancel.set()
        close = getattr(self.engine.backend, 'close', None)
        if close:
            close()
