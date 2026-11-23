"""Explicit model downloads and side-by-side managed runtime updates."""
import threading
import platform
from qtpy.QtCore import Signal
from qtpy.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QComboBox, QLabel, QListWidget, QProgressBar, QFileDialog, QFrame)
from . import downloads


class LibraryDialog(QDialog):
    update_signal = Signal(str, object)

    def __init__(self, config, parent=None, auto=False, downloads_agreed=False):
        super().__init__(parent)
        self.config, self.items, self.runtime_item = config, [], None
        self.busy, self.pending_close = False, False
        self.pending_plan, self.step = None, ''
        self.downloads_agreed = downloads_agreed     # the user already said yes (the chat's offer)
        self.cancel = threading.Event()
        self.setWindowTitle('Local model')
        self.resize(720, 260)
        outer = QVBoxLayout(self)
        # the largest model this computer's graphics memory runs is offered first (user
        # 2026-11-23: Qwen 27B in the list, the default chosen from the GPU memory)
        from .hardware import LOCAL_MODELS, recommend_for_this_computer
        try:
            recommended, why = recommend_for_this_computer()
        except Exception:
            recommended, why = LOCAL_MODELS[1][0], ''
        # one button does it all (user 2026-11-23: "too complex"): it finds the model and
        # llama.cpp on this computer (LM Studio's too), else downloads them
        intro = QLabel('The assistant can run on this computer: private, free, no API key. '
                       'One click finds a model and llama.cpp already on this computer (for example '
                       "LM Studio's), or downloads them once.")
        intro.setWordWrap(True)
        outer.addWidget(intro)
        self.auto_button = QPushButton('Set up automatically')
        self.auto_button.setMinimumHeight(40)
        self.auto_button.clicked.connect(self.set_up_automatically)
        outer.addWidget(self.auto_button)
        self.recommendation = QLabel('Recommended for this computer: ' + why if why else '')
        self.recommendation.setWordWrap(True)
        outer.addWidget(self.recommendation)
        # models already on this computer (LM Studio, Ollama, Hugging Face cache, ours): reuse one
        outer.addWidget(QLabel('Or use a model already on this computer:'))
        row = QHBoxLayout()
        self.found = QComboBox()
        self.found.setToolTip('Models found in LM Studio, Ollama, the Hugging Face cache and this chat’s downloads')
        row.addWidget(self.found, 1)
        self.use_found = QPushButton('Use')
        self.use_found.clicked.connect(self.use_found_model)
        row.addWidget(self.use_found)
        outer.addLayout(row)
        self.fill_found(recommended)
        self.advanced_button = QPushButton('Advanced options ▸')
        self.advanced_button.setFlat(True)
        self.advanced_button.clicked.connect(self.toggle_advanced)
        outer.addWidget(self.advanced_button)
        self.advanced = QFrame()
        layout = QVBoxLayout(self.advanced)
        layout.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.advanced, 1)
        self.advanced.setVisible(False)
        layout.addWidget(QLabel('Hugging Face GGUF models'))
        row = QHBoxLayout()
        self.query = QLineEdit(recommended.split('/')[-1])
        row.addWidget(self.query)
        search = QPushButton('Search')
        search.clicked.connect(lambda: self.run('repositories', lambda: downloads.search_models(self.query.text().strip())))
        row.addWidget(search)
        layout.addLayout(row)
        self.repositories = QComboBox()
        self.repositories.setEditable(True)
        for repo, label, _need in LOCAL_MODELS:
            self.repositories.addItem(repo)
            self.repositories.setItemData(self.repositories.count() - 1, label, 3)    # Qt.ToolTipRole
        self.repositories.setCurrentText(recommended)
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
        outer.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        outer.addWidget(self.progress)
        stop = QPushButton('Cancel')
        stop.clicked.connect(self.cancel.set)
        outer.addWidget(stop)
        self.update_signal.connect(self.receive)
        if auto:
            self.set_up_automatically()

    def toggle_advanced(self):
        show = not self.advanced.isVisible()
        self.advanced.setVisible(show)
        self.advanced_button.setText('Advanced options ' + ('▾' if show else '▸'))
        if show:
            self.resize(self.width(), max(self.height(), 640))

    def fill_found(self, recommended):
        from . import discover
        try:
            storage = self.config.storage()
        except Exception:
            storage = None
        try:
            models = discover.local_models(storage)
        except Exception:
            models = []
        self.found.clear()
        for m in models:
            self.found.addItem(f"{m['name']}  ·  {m['gb']:.1f} GB  ·  {m['source']}", str(m['path']))
            self.found.setItemData(self.found.count() - 1, m['name'], 32)        # Qt.UserRole: its name
        if not models:
            self.found.addItem('No model found on this computer', None)
        self.found.setEnabled(bool(models))
        self.use_found.setEnabled(bool(models))
        best = discover.pick_model(models, recommended) if models else None
        if best is not None:
            self.found.setCurrentIndex(max(0, self.found.findData(str(best))))

    def say(self, text):
        self.update_signal.emit('say', text)

    def use_found_model(self):
        """Use the chosen model: look for a working llama.cpp first (no network), then ask
        before downloading one."""
        from pathlib import Path
        from . import discover
        path = self.found.currentData()
        if path:
            name = self.found.itemData(self.found.currentIndex(), 32)
            self.run('plan', lambda: discover.plan(self.config, Path(path), name, self.say))

    def set_up_automatically(self):
        """Look on this computer first (no network); anything missing is downloaded only after
        the user has agreed to the list of what comes from where (user 2026-11-23)."""
        from . import discover
        self.run('plan', lambda: discover.plan(self.config, say=self.say))

    def carry_out(self, plan):
        """After the look-up: ask before any download, then download (progress bar) and use."""
        from qtpy.QtWidgets import QMessageBox
        from . import discover
        wanted = discover.download_text(plan)
        if wanted and not self.downloads_agreed:
            text = 'To run the assistant on this computer, this will download from the internet:\n\n' + wanted
            if plan['problems']:
                text += ('\n\nllama.cpp found on this computer does not start here:\n'
                         + '\n'.join('• ' + p for p in plan['problems'][:3]))
            text += '\n\nDownloads are checked (SHA256) and kept in the chat’s own folder. Download now?'
            answer = QMessageBox.question(self, 'Download for the local model', text,
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                self.status.setText('Nothing downloaded. Choose a model already on this computer, '
                                    'or an online service (Model button).')
                return
        self.run('auto_ready', lambda: discover.run_plan(self.config, plan,
                                                         lambda p: self.update_signal.emit('progress', p),
                                                         self.cancel, self.say))

    def run(self, kind, action):
        if self.busy:
            return
        self.busy = True
        self.cancel.clear()
        self.step = ''
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
            self.status.setText((self.step + '\n' if self.step else '') + f'{done / 1024**2:,.1f} MiB downloaded'
                                + (f' / {total / 1024**2:,.1f} MiB ({done * 100 / total:.0f} %)' if total else ''))
        elif kind == 'say':                 # the step under way, in plain words
            self.step = value
            self.status.setText(value)
            self.progress.setRange(0, 0)    # busy until a download reports its size
        elif kind == 'plan':
            self.pending_plan = value       # carried out once this worker has finished
        elif kind == 'repositories':
            self.repositories.clear()
            self.repositories.addItems(value)
            self.status.setText(f'{len(value)} repositories found')
        elif kind == 'files':
            self.items = value
            self.files.clear()
            self.files.addItems([f"{i['name']} · {i['size'] / 1024**3:.2f} GiB" for i in value])
            # Q4_K_M: the quantization the recommendations are sized for
            pick = next((k for k, i in enumerate(value) if 'q4_k_m' in i['name'].lower()), -1)
            if pick >= 0:
                self.files.setCurrentRow(pick)
            self.status.setText(f'{len(value)} GGUF files found. Select one quantization'
                                + (' (Q4_K_M selected: a good balance of size and quality).' if pick >= 0 else '.'))
        elif kind == 'runtime_release':
            self.runtime_item = value
            self.install.setEnabled(True)
            self.status.setText('Available compatible build: ' + value['tag'] + ' / ' + value['backend'])
        elif kind == 'auto_ready':          # discover.setup has filled the config
            self.config.save_connection()
            self.config.save_performance()
            self.done_message = value
            self.status.setText(value)
            self.progress.setRange(0, 100)
            self.progress.setValue(100)
            # done: the window closes and the chat says what was chosen (user 2026-11-23: after
            # "Use" nothing seemed to happen, 0% and "close this window")
            self.busy = False
            self.accept()
        elif kind in ('model_ready', 'runtime_ready'):
            key = 'model' if kind == 'model_ready' else 'executable'
            self.config.runtime[key] = str(value)
            if kind == 'model_ready':
                from pathlib import Path
                self.config.runtime['model_name'] = Path(str(value)).stem
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
            # never a stalled bar with no word (user 2026-11-23): say what failed, in a window
            self.pending_plan = None
            self.status.setText('Failed: ' + str(value))
            if not self.pending_close:
                from qtpy.QtWidgets import QMessageBox
                QMessageBox.warning(self, 'Local model', str(value) + '\n\nYou can try again, choose another '
                                    'model, or use an online service instead (Model button).')
        elif kind == 'finished':
            self.busy = False
            if self.progress.maximum() == 0:
                self.progress.setRange(0, 100)
                self.progress.setValue(0)
            if self.pending_close:
                self.reject()
            elif self.pending_plan is not None:
                plan, self.pending_plan = self.pending_plan, None
                self.carry_out(plan)

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
