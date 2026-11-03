from dataclasses import asdict
from qtpy.QtWidgets import (QDialog, QFormLayout, QComboBox, QLineEdit, QLabel,
    QDialogButtonBox, QPushButton)
from .config import Config
from .credentials import set_key, delete_key

PRESETS = {'local': 'http://127.0.0.1:1234/v1', 'openai': 'https://api.openai.com/v1',
           'anthropic': 'https://api.anthropic.com/v1', 'openrouter': 'https://openrouter.ai/api/v1',
           'groq': 'https://api.groq.com/openai/v1',
           'iteracompute': 'https://api.iteracompute.com/v1', 'nvidia': 'https://integrate.api.nvidia.com/v1',
           'compatible': 'https://your-provider.example/v1'}
# the model filled in when a provider is chosen: on OpenRouter a free model
# that reads images, calls tools and has a 1M-token context (checked
# 2026-11-02; thinkingmachines/inkling:free is refused to apps not on
# OpenRouter's approved list); Groq's free tier (7,000 input tokens/min) is too
# small for a turn with an application's tools, its paid tier is not
# Free tiers listed at github.com/nejib1/Free-LLM (2026-11-03): IteraCompute's
# model list marks qwen/qwen3.8-27b free; NVIDIA NIM lists the Nemotron VL id
# (Hetzner's inference API, listed there too, turned out not to be free)
DEFAULT_MODELS = {'openrouter': 'openrouter/free', 'groq': 'qwen/qwen3.8-27b',
                  'iteracompute': 'qwen/qwen3.8-27b', 'nvidia': 'nvidia/nemotron-3.5-super-vl-120b-a12b'}


class ConnectionDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config, self.result_config = config, None
        self.setWindowTitle('Model connection and secure credentials')
        form = QFormLayout(self)
        self.provider = QComboBox()
        for key, label in [('local', 'Local model (preferred)'), ('openai', 'OpenAI API'), ('anthropic', 'Claude / Anthropic API'),
                           ('openrouter', 'OpenRouter (free router, recommended)'), ('groq', 'Groq (paid tier)'),
                           ('iteracompute', 'IteraCompute (free Qwen3.8-27B, slow)'), ('nvidia', 'NVIDIA NIM (free)'),
                           ('compatible', 'Custom OpenAI-compatible API')]:
            self.provider.addItem(label, key)
        self.provider.setCurrentIndex(self.provider.findData(config.provider))
        form.addRow('Provider', self.provider)
        self.url = QLineEdit(config.base_url)
        form.addRow('API base URL', self.url)
        self.model = QLineEdit(config.model)
        form.addRow('Exact model ID', self.model)
        browse = QPushButton('List models…')
        browse.setToolTip('Ask this provider which models your key can use (the key typed below, else the stored one) '
                          'and pick one')
        browse.clicked.connect(self.choose_model)
        form.addRow('', browse)
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
        self.capability.setCurrentText({'local': 'llama_cpp', 'openai': 'reasoning_effort', 'groq': 'reasoning_effort',
                                        'iteracompute': 'reasoning_effort',
                                        'anthropic': 'anthropic_adaptive'}.get(provider, 'unsupported'))
        if provider in DEFAULT_MODELS and (not self.model.text().strip() or self.model.text().strip() in DEFAULT_MODELS.values()
                                           or provider != self.config.provider):
            self.model.setText(DEFAULT_MODELS[provider])
        self.key.clear()
        self.update_note()

    def candidate(self, require_model=True):
        value = asdict(self.config)
        provider = self.provider.currentData()
        value.update(provider=provider, base_url=self.url.text().strip(), model=self.model.text().strip(),
            thinking_backend=self.capability.currentText(), thinking='default', thinking_strength='default',
            api_key_env='', runtime=value['runtime'] if provider == 'local' else {})
        if not value['model']:
            if require_model:
                raise ValueError('Enter an exact model ID')
            value['model'] = 'unknown'
        return Config(**value)

    def available_models(self):
        """Model ids the provider's /models lists for this key (free ones first
        when the provider marks them), or raises with the provider's answer."""
        import httpx
        candidate = self.candidate(require_model=False)
        key = self.key.text().strip()
        if not key and candidate.provider != 'local':
            from .credentials import get_key
            key = get_key(candidate) or ''
        reply = httpx.get(candidate.base_url.rstrip('/') + '/models', timeout=20,
                          headers={'Authorization': 'Bearer ' + key} if key else {})
        if reply.status_code >= 400:
            raise ValueError(f'The provider answered HTTP {reply.status_code}: {reply.text[:300]}')
        models = reply.json().get('data', [])
        free = [m['id'] for m in models if m.get('is_free') or str(m.get('id', '')).endswith(':free')]
        return free + sorted(m['id'] for m in models if m.get('id') and m['id'] not in free)

    def choose_model(self):
        from qtpy.QtWidgets import QInputDialog
        try:
            models = self.available_models()
        except Exception as exc:
            self.error.setText(str(exc))
            return
        if not models:
            self.error.setText('The provider listed no models for this key.')
            return
        current = models.index(self.model.text()) if self.model.text() in models else 0
        chosen, ok = QInputDialog.getItem(self, 'Models', f'{len(models)} models available:', models, current, False)
        if ok and chosen:
            self.model.setText(chosen)
            self.error.setText('')

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
