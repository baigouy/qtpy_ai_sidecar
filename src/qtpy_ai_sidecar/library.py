"""Explicit model downloads and side-by-side managed runtime updates."""
import threading
import platform
from qtpy.QtCore import Signal
from qtpy.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QComboBox, QLabel, QListWidget, QProgressBar, QFileDialog)
from . import downloads


class LibraryDialog(QDialog):
    update_signal = Signal(str, object)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config, self.items, self.runtime_item = config, [], None
        self.busy, self.pending_close = False, False
        self.cancel = threading.Event()
        self.setWindowTitle('Local models and llama.cpp updates')
        self.resize(720, 600)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Hugging Face GGUF models'))
        row = QHBoxLayout()
        self.query = QLineEdit('Qwen3.5-9B-GGUF')
        row.addWidget(self.query)
        search = QPushButton('Search')
        search.clicked.connect(lambda: self.run('repositories', lambda: downloads.search_models(self.query.text().strip())))
        row.addWidget(search)
        layout.addLayout(row)
        self.repositories = QComboBox()
        self.repositories.setEditable(True)
        self.repositories.addItem('lmstudio-community/Qwen3.5-9B-GGUF')
        layout.addWidget(self.repositories)
        files = QPushButton('List GGUF files and sizes')
        files.clicked.connect(lambda: self.run('files', lambda: downloads.model_files(self.repositories.currentText().strip())))
        layout.addWidget(files)
        self.files = QListWidget()
        layout.addWidget(self.files, 1)
        get = QPushButton('Download selected GGUF and use it')
        get.clicked.connect(self.get_model)
        layout.addWidget(get)
        local_model = QPushButton('Use an existing GGUF…')
        local_model.clicked.connect(self.existing_model)
        layout.addWidget(local_model)
        row = QHBoxLayout()
        self.backend = QComboBox()
        self.backend.addItems(['metal', 'cpu'] if platform.system() == 'Darwin' else ['vulkan', 'cpu'])
        row.addWidget(self.backend)
        check = QPushButton('Check official llama.cpp updates')
        check.clicked.connect(lambda: self.run('runtime_release', lambda: downloads.check_runtime(self.backend.currentText())))
        row.addWidget(check)
        layout.addLayout(row)
        self.install = QPushButton('Install checked runtime in managed folder')
        self.install.setEnabled(False)
        self.install.clicked.connect(self.get_runtime)
        layout.addWidget(self.install)
        local_runtime = QPushButton('Use an existing llama-server executable…')
        local_runtime.clicked.connect(self.existing_runtime)
        layout.addWidget(local_runtime)
        note = QLabel('Downloads start only when requested. SHA256 is checked before installation. Updates use a new folder and apply on the next model start. GPU drivers are managed by your OS. Runtime builds are selected for Windows/macOS/Linux and x64/ARM64; Linux official binaries require a compatible Ubuntu/glibc system. You can also choose an existing binary. Single-file GGUFs are supported.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.status = QLabel('Ready')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)
        stop = QPushButton('Cancel current operation')
        stop.clicked.connect(self.cancel.set)
        layout.addWidget(stop)
        self.update_signal.connect(self.receive)

    def run(self, kind, action):
        if self.busy:
            return
        self.busy = True
        self.cancel.clear()
        self.status.setText('Working…')
        self.progress.setRange(0, 0)
        def work():
            try:
                self.update_signal.emit(kind, action())
            except Exception as exc:
                self.update_signal.emit('error', str(exc))
            finally:
                self.update_signal.emit('finished', None)
        threading.Thread(target=work, daemon=True).start()

    def receive(self, kind, value):
        if kind == 'progress':
            total, done = value['total'], value['downloaded']
            self.progress.setRange(0, 100 if total else 0)
            if total:
                self.progress.setValue(int(done * 100 / total))
            self.status.setText(f'{done / 1024**2:,.1f} MiB downloaded' + (f' / {total / 1024**2:,.1f} MiB' if total else ''))
        elif kind == 'repositories':
            self.repositories.clear()
            self.repositories.addItems(value)
            self.status.setText(f'{len(value)} repositories found')
        elif kind == 'files':
            self.items = value
            self.files.clear()
            self.files.addItems([f"{i['name']} · {i['size'] / 1024**3:.2f} GiB" for i in value])
            self.status.setText(f'{len(value)} GGUF files found. Select one quantization.')
        elif kind == 'runtime_release':
            self.runtime_item = value
            self.install.setEnabled(True)
            self.status.setText('Available compatible build: ' + value['tag'] + ' / ' + value['backend'])
        elif kind in ('model_ready', 'runtime_ready'):
            key = 'model' if kind == 'model_ready' else 'executable'
            self.config.runtime[key] = str(value)
            self.config.runtime.setdefault('gpu_layers', 0 if self.backend.currentText() == 'cpu' else 99)
            self.config.provider = 'local'
            self.config.base_url = 'http://127.0.0.1:1234/v1'
            self.config.api_key_env = ''
            self.config.thinking_backend = 'llama_cpp'
            if kind == 'runtime_ready':
                self.config.runtime['gpu_layers'] = 0 if self.backend.currentText() == 'cpu' else 99
            self.config.save_connection()
            self.config.save_performance()
            self.status.setText('Ready for next model start: ' + str(value))
        elif kind == 'error':
            self.status.setText(str(value))
        elif kind == 'finished':
            self.busy = False
            if self.progress.maximum() == 0:
                self.progress.setRange(0, 100)
                self.progress.setValue(0)
            if self.pending_close:
                self.reject()

    def get_model(self):
        index = self.files.currentRow()
        if 0 <= index < len(self.items):
            item = self.items[index]
            self.run('model_ready', lambda: downloads.download_model(item, self.config.storage(),
                lambda p: self.update_signal.emit('progress', p), self.cancel))

    def get_runtime(self):
        if self.runtime_item:
            item = self.runtime_item
            self.run('runtime_ready', lambda: downloads.install_runtime(item, self.config.storage(),
                lambda p: self.update_signal.emit('progress', p), self.cancel))

    def existing_model(self):
        if self.busy:
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Choose GGUF', '', 'GGUF (*.gguf)')
        if path:
            self.receive('model_ready', path)

    def existing_runtime(self):
        if self.busy:
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Choose llama-server executable')
        if path:
            self.receive('runtime_ready', path)

    def reject(self):
        if self.busy:
            self.pending_close = True
            self.cancel.set()
            self.status.setText('Cancelling; waiting for current network read to finish…')
        else:
            super().reject()
