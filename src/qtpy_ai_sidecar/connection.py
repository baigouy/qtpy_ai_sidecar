from dataclasses import asdict
from qtpy.QtWidgets import (QDialog, QFormLayout, QComboBox, QLineEdit, QLabel,
    QDialogButtonBox, QPushButton)
from .config import Config
from .credentials import set_key, delete_key

PRESETS = {'local': 'http://127.0.0.1:1234/v1', 'openai': 'https://api.openai.com/v1',
           'anthropic': 'https://api.anthropic.com/v1', 'openrouter': 'https://openrouter.ai/api/v1',
           'groq': 'https://api.groq.com/openai/v1',
           'iteracompute': 'https://api.iteracompute.com/v1', 'nvidia': 'https://integrate.api.nvidia.com/v1',
           'mistral': 'https://api.mistral.ai/v1', 'compatible': 'https://your-provider.example/v1'}
# the model filled in when a provider is chosen: on OpenRouter a free model
# that reads images, calls tools and has a 1M-token context (checked
# 2026-11-02; thinkingmachines/inkling:free is refused to apps not on
# OpenRouter's approved list); Groq's free tier (7,000 input tokens/min) is too
# small for a turn with an application's tools, its paid tier is not
# Free tiers listed at github.com/nejib1/Free-LLM (2026-11-03): IteraCompute's
# model list marks qwen/qwen3.8-27b free; NVIDIA NIM lists the Nemotron VL id
# (Hetzner's inference API, listed there too, turned out not to be free);
# Mistral Large 4 (1M context, reads images; mistral-large-latest was still
# Large 3 on Mistral's model list, 2026-11-03). Mistral also serves Z.ai's GLM
# models (zai-glm-*) with the same key; 'List models…' shows them.
DEFAULT_MODELS = {'openrouter': 'openrouter/free', 'groq': 'qwen/qwen3.8-27b',
                  'iteracompute': 'qwen/qwen3.8-27b', 'nvidia': 'nvidia/nemotron-3.5-super-vl-120b-a12b',
                  'mistral': 'mistral-large-4'}
READS_IMAGES = '  (reads images)'
# how these providers' keys begin: a key pasted with the wrong provider still
# selected would otherwise replace that provider's stored key (2026-11-03)
KEY_PREFIXES = {'openrouter': 'sk-or-', 'anthropic': 'sk-ant-', 'groq': 'gsk_', 'nvidia': 'nvapi-'}


def one_name_per_model(models, current=''):
    """Mistral lists every alias as a model of its own (mistral-medium had eight
    names): keep one entry per model, named by the current model when it is one
    of them, else its '-latest' alias, else its shortest name."""
    kept, seen = [], set()
    for m in models:
        names = {n for n in [m.get('id'), *(m.get('aliases') or [])] if n}
        if not names or names & seen:
            continue
        seen |= names
        latest = sorted((n for n in names if n.endswith('-latest')), key=len)
        name = current if current in names else (latest or sorted(names, key=lambda n: (len(n), n)))[0]
        kept.append(dict(m, id=name))
    return kept


def model_info(m):
    """What a provider's model list says of one model: reads images, thinks,
    context window (None when it does not say). Mistral: capabilities.vision /
    .reasoning and max_context_length; OpenRouter: architecture.input_modalities,
    supported_parameters and context_length."""
    caps = m.get('capabilities') or {}
    params = m.get('supported_parameters') or []
    return {'vision': bool(caps.get('vision') or 'image' in (m.get('architecture') or {}).get('input_modalities', [])),
            'reasoning': bool(caps.get('reasoning') or 'reasoning' in params or 'include_reasoning' in params),
            'context': m.get('max_context_length') or m.get('context_length') or m.get('context_window')}


def list_models(config, key=''):
    """(model ids, {id: model_info}) from the provider's /models for this key
    (else the stored one); free ones first when the provider marks them.
    Raises with the provider's answer. Used by 'List models…' and the
    composer's model picker."""
    import httpx
    if not key and config.provider != 'local':
        from .credentials import get_key
        key = get_key(config) or ''
    reply = httpx.get(config.base_url.rstrip('/') + '/models', timeout=20,
                      headers={'Authorization': 'Bearer ' + key} if key else {})
    if reply.status_code >= 400:
        raise ValueError(f'The provider answered HTTP {reply.status_code}: {reply.text[:300]}')
    models = reply.json().get('data', [])
    # Mistral gives capabilities: keep the chat models that call tools (no
    # embedding, OCR or speech models) and note which read images
    models = [m for m in models if 'capabilities' not in m
              or (m['capabilities'].get('completion_chat') and m['capabilities'].get('function_calling'))]
    models = one_name_per_model(models, config.model)
    info = {m['id']: model_info(m) for m in models}
    free = [m['id'] for m in models if m.get('is_free') or str(m.get('id', '')).endswith(':free')]
    return free + sorted(m['id'] for m in models if m.get('id') and m['id'] not in free), info


class ConnectionDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config, self.result_config = config, None
        self.vision_models = set()
        self.setWindowTitle('Model connection and secure credentials')
        form = QFormLayout(self)
        self.provider = QComboBox()
        self.fill_providers(config.provider)
        form.addRow('Provider', self.provider)
        # the user's own providers (any OpenAI-compatible API): add, edit, remove
        from qtpy.QtWidgets import QHBoxLayout
        manage = QHBoxLayout()
        self.add_provider = QPushButton('Add provider…')
        self.add_provider.setToolTip('Add another OpenAI-compatible API (its name, address and model), kept for next time')
        self.add_provider.clicked.connect(lambda: self.edit_provider(None))
        self.edit_provider_button = QPushButton('Edit…')
        self.edit_provider_button.clicked.connect(lambda: self.edit_provider(self.provider.currentData()))
        self.remove_provider_button = QPushButton('Remove')
        self.remove_provider_button.clicked.connect(self.remove_provider)
        for button in (self.add_provider, self.edit_provider_button, self.remove_provider_button):
            manage.addWidget(button)
        form.addRow('', manage)
        self.sync_provider_buttons()
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

    BUILTIN_LABELS = [('local', 'Local model (preferred)'), ('openai', 'OpenAI API'), ('anthropic', 'Claude / Anthropic API'),
                      ('openrouter', 'OpenRouter (free router, recommended)'), ('groq', 'Groq (paid tier)'),
                      ('iteracompute', 'IteraCompute (free Qwen3.8-27B, slow)'), ('nvidia', 'NVIDIA NIM (free)'),
                      ('mistral', 'Mistral AI API'), ('compatible', 'Custom OpenAI-compatible API')]

    def fill_providers(self, current):
        from . import providers
        self.provider.blockSignals(True)
        self.provider.clear()
        for key, label in self.BUILTIN_LABELS:
            self.provider.addItem(label, key)
        for entry in providers.load():
            self.provider.addItem(entry['label'] + '  (yours)', entry['key'])
        self.provider.setCurrentIndex(max(0, self.provider.findData(current)))
        self.provider.blockSignals(False)
        self.sync_provider_buttons()

    def sync_provider_buttons(self):
        from . import providers
        custom = self.provider.currentData() not in providers.BUILTIN
        if hasattr(self, 'edit_provider_button'):
            self.edit_provider_button.setEnabled(custom)
            self.remove_provider_button.setEnabled(custom)

    def edit_provider(self, key):
        """Add a provider (key None) or edit one of the user's; it is then selected."""
        from . import providers
        dialog = ProviderDialog(providers.find(key) if key else None, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.fill_providers(dialog.saved_key)
            self.changed()

    def remove_provider(self):
        from . import providers
        key = self.provider.currentData()
        if key in providers.BUILTIN:
            return
        providers.remove(key)
        self.fill_providers('compatible')
        self.changed()
        self.error.setText('Provider removed. Its stored key, if any, stays in the OS vault until deleted.')

    def update_note(self):
        local = self.provider.currentData() == 'local'
        self.note.setText('Local mode uses the sidecar-managed runtime. Configure a model and runtime in Model Library. For LM Studio or another separately managed server, use Custom OpenAI-compatible API; this sidecar cannot control its hardware.' if local else
            'API mode sends conversation and application tool results to this endpoint. Paid providers may charge; a compatible local server may be free. ChatGPT/Claude subscriptions do not supply API credits. Keys are saved only in the OS credential vault. Switching connections starts a fresh working conversation.')

    def changed(self):
        from . import providers
        provider = self.provider.currentData()
        self.sync_provider_buttons()
        custom = providers.find(provider)
        self.url.setText(custom['base_url'] if custom else PRESETS[provider])
        self.capability.setCurrentText(custom['thinking_backend'] if custom else
                                       {'local': 'llama_cpp', 'openai': 'reasoning_effort', 'groq': 'reasoning_effort',
                                        'iteracompute': 'reasoning_effort', 'mistral': 'reasoning_effort',
                                        'anthropic': 'anthropic_adaptive'}.get(provider, 'unsupported'))
        remembered = self.config.saved_models().get(provider) or (custom or {}).get('model')
        if provider == self.config.provider and self.config.model not in ('', 'unknown'):
            remembered = self.config.model
        if remembered and provider != 'local':
            self.model.setText(remembered)            # the model last used with this provider
        elif provider in DEFAULT_MODELS and (not self.model.text().strip() or self.model.text().strip() in DEFAULT_MODELS.values()
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
        models, info = list_models(self.candidate(require_model=False), self.key.text().strip())
        self.vision_models = {m for m, i in info.items() if i['vision']}
        return models

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
        labels = [m + READS_IMAGES if m in self.vision_models else m for m in models]
        chosen, ok = QInputDialog.getItem(self, 'Models', f'{len(models)} models available:', labels, current, False)
        if ok and chosen:
            self.model.setText(chosen.removesuffix(READS_IMAGES))
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
            from . import providers
            prefix = KEY_PREFIXES.get(candidate.provider) or (providers.find(candidate.provider) or {}).get('key_prefix')
            if self.key.text().strip() and prefix and not self.key.text().strip().startswith(prefix):
                raise ValueError(f'This is not a key for {self.provider.currentText()} (its keys begin with '
                                 f'"{prefix}"). Choose the provider the key belongs to; nothing was saved.')
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


class ProviderDialog(QDialog):
    """Name, address, model, thinking capability and key prefix of a provider
    the user adds; its key is entered afterwards in the connection dialog."""
    def __init__(self, entry=None, parent=None):
        super().__init__(parent)
        from .providers import THINKING
        entry = entry or {}
        self.key, self.saved_key = entry.get('key'), None
        self.setWindowTitle('Edit provider' if entry else 'Add a provider')
        self.setMinimumWidth(520)              # room for a full API address
        form = QFormLayout(self)
        self.label = QLineEdit(entry.get('label', ''))
        self.label.setPlaceholderText('e.g. Z.ai, DeepSeek, my lab server')
        form.addRow('Name', self.label)
        self.url = QLineEdit(entry.get('base_url', ''))
        self.url.setPlaceholderText('https://api.example.com/v1 (OpenAI-compatible)')
        form.addRow('API base URL', self.url)
        self.model = QLineEdit(entry.get('model', ''))
        self.model.setPlaceholderText('filled in when this provider is chosen (List models… can pick one later)')
        form.addRow('Model', self.model)
        self.thinking = QComboBox()
        self.thinking.addItems(THINKING)
        self.thinking.setCurrentText(entry.get('thinking_backend', 'unsupported'))
        form.addRow('Thinking capability', self.thinking)
        self.prefix = QLineEdit(entry.get('key_prefix', ''))
        self.prefix.setPlaceholderText('optional, e.g. sk-: a key not starting with it is refused')
        form.addRow('Keys begin with', self.prefix)
        note = QLabel('The API key is entered in the connection dialog and kept in the OS vault, never in this list.')
        note.setWordWrap(True)
        form.addRow(note)
        self.error = QLabel()
        self.error.setWordWrap(True)
        form.addRow(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def save(self):
        from . import providers
        try:
            self.saved_key = providers.save({'key': self.key, 'label': self.label.text(), 'base_url': self.url.text(),
                                             'model': self.model.text(), 'thinking_backend': self.thinking.currentText(),
                                             'key_prefix': self.prefix.text()})
            self.accept()
        except Exception as exc:
            self.error.setText(str(exc))
