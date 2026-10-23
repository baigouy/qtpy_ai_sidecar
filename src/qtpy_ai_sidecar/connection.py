from dataclasses import asdict
from qtpy.QtWidgets import (QDialog, QFormLayout, QComboBox, QLineEdit, QLabel,
    QDialogButtonBox, QPushButton)
from .config import Config
from .credentials import set_key, delete_key

PRESETS = {'local': 'http://127.0.0.1:1234/v1', 'openai': 'https://api.openai.com/v1',
           'anthropic': 'https://api.anthropic.com/v1', 'openrouter': 'https://openrouter.ai/api/v1',
           'compatible': 'https://your-provider.example/v1'}


class ConnectionDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config, self.result_config = config, None
        self.setWindowTitle('Model connection and secure credentials')
        form = QFormLayout(self)
        self.provider = QComboBox()
        for key, label in [('local', 'Local model (preferred)'), ('openai', 'OpenAI API'), ('anthropic', 'Claude / Anthropic API'),
                           ('openrouter', 'OpenRouter'), ('compatible', 'Custom OpenAI-compatible API')]:
            self.provider.addItem(label, key)
        self.provider.setCurrentIndex(self.provider.findData(config.provider))
        form.addRow('Provider', self.provider)
        self.url = QLineEdit(config.base_url)
        form.addRow('API base URL', self.url)
        self.model = QLineEdit(config.model)
        form.addRow('Exact model ID', self.model)
        self.capability = QComboBox()
        self.capability.addItems(['unsupported', 'llama_cpp', 'reasoning_effort', 'anthropic_adaptive', 'anthropic_budget'])
        self.capability.setCurrentText(config.thinking_backend)
        form.addRow('Thinking capability', self.capability)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText('Leave blank to keep the key in the OS vault')
        form.addRow('New API key', self.key)
        self.note = QLabel('')
        self.note.setWordWrap(True)
        form.addRow(self.note)
        remove = QPushButton('Delete stored key for this endpoint')
        remove.clicked.connect(self.delete)
        form.addRow(remove)
        self.error = QLabel()
        self.error.setWordWrap(True)
        form.addRow(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.provider.currentIndexChanged.connect(self.changed)
        self.update_note()

    def update_note(self):
        local = self.provider.currentData() == 'local'
        self.note.setText('Local mode uses the sidecar-managed runtime. Configure a model and runtime in Model Library. For LM Studio or another separately managed server, use Custom OpenAI-compatible API; this sidecar cannot control its hardware.' if local else
            'API mode sends conversation and application tool results to this endpoint. Paid providers may charge; a compatible local server may be free. ChatGPT/Claude subscriptions do not supply API credits. Keys are saved only in the OS credential vault. Switching connections starts a fresh working conversation.')

    def changed(self):
        provider = self.provider.currentData()
        self.url.setText(PRESETS[provider])
        self.capability.setCurrentText({'local': 'llama_cpp', 'openai': 'reasoning_effort', 'anthropic': 'anthropic_adaptive'}.get(provider, 'unsupported'))
        self.key.clear()
        self.update_note()

    def candidate(self):
        value = asdict(self.config)
        provider = self.provider.currentData()
        value.update(provider=provider, base_url=self.url.text().strip(), model=self.model.text().strip(),
            thinking_backend=self.capability.currentText(), thinking='default', thinking_strength='default',
            api_key_env='', runtime=value['runtime'] if provider == 'local' else {})
        if not value['model']:
            raise ValueError('Enter an exact model ID')
        return Config(**value)

    def delete(self):
        try:
            delete_key(self.candidate())
            self.key.clear()
            self.error.setText('Stored key deleted for this provider endpoint.')
        except Exception as exc:
            self.error.setText(str(exc))

    def save(self):
        try:
            candidate = self.candidate()
            if self.key.text().strip():
                set_key(candidate, self.key.text())
                self.key.clear()
            candidate.save_connection()
            candidate.save_performance()
            self.result_config = candidate
            self.accept()
        except Exception as exc:
            self.error.setText(str(exc))

    def done(self, result):
        self.key.clear()
        super().done(result)
