"""One entry for the model (user 2026-11-23: "a unified option/config menu for models, it should
then ask whether global or local and depending on the choice choose the right interface" /
"it was not obvious which one was running" / "just launching MCP should be easy and can be used
with any local agent" / "for the API in fact it can also be local through LM Studio local
server"): the window says what runs now, then the user says where the assistant runs and sees
only the settings of that choice."""
from pathlib import Path
from urllib.parse import urlsplit

from qtpy.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton


def running(config):
    """What the chat uses now, in a few words: 'On this computer · Qwen3.8-27B-Q4_K_M',
    'Local server · LM Studio · qwen3.8-27b' or 'Online · Mistral AI API · mistral-large-4'."""
    if config.provider == 'local':
        model = str(config.runtime.get('model') or '')
        name = config.runtime.get('model_name') or (Path(model.replace('\\', '/')).stem if model else '')
        return 'On this computer · ' + (name or 'no model set up yet')
    from .config import LOOPBACK_HOSTS
    from .discover import server_name
    if urlsplit(str(config.base_url or '')).hostname in LOOPBACK_HOSTS:
        return f'Local server · {server_name(config.base_url) or config.base_url} · {config.model}'
    from . import providers
    from .connection import ConnectionDialog
    name = ((providers.find(config.provider) or {}).get('label')
            or dict(ConnectionDialog.BUILTIN_LABELS).get(config.provider) or config.provider)
    return f'Online · {name} · {config.model}'


class ModelChoice(QDialog):
    """Ends with self.choice = 'local', 'online', 'other_app' or a server dict from
    discover.local_servers (None when closed)."""

    def __init__(self, config, parent=None, other_app=False, servers=()):
        super().__init__(parent)
        self.choice = None
        self.setWindowTitle('Model')
        layout = QVBoxLayout(self)
        self.current = QLabel('<b>Now:</b> ' + running(config))
        self.current.setWordWrap(True)
        layout.addWidget(self.current)
        layout.addWidget(QLabel('Where should the assistant run?'))
        self.local_button = QPushButton('On this computer\nprivate, free, no API key; needs a graphics card to be fast')
        choices = [(self.local_button, 'local')]
        self.server_buttons = []
        for server in servers:          # LM Studio's or Ollama's server, running now
            loaded = server.get('loaded') or []
            what = f'model loaded: {loaded[0]}' if loaded else f"{len(server['models'])} models"
            button = QPushButton(f"{server['name']}'s server on this computer\n{what}; "
                                 'private, no API key; nothing is sent online')
            self.server_buttons.append(button)
            choices.append((button, server))
        self.online_button = QPushButton('Online service\nfast on any computer; needs an API key (some are free); '
                                         'your messages and figure previews are sent to the provider')
        choices.append((self.online_button, 'online'))
        self.other_app_button = None
        if other_app:
            self.other_app_button = QPushButton(f'Another AI app (Claude Desktop, LM Studio, Codex...)\n'
                                                f'it uses {config.application} through its MCP server; '
                                                'this chat is not needed')
            choices.append((self.other_app_button, 'other_app'))
        for button, choice in choices:
            button.setMinimumHeight(56)
            button.clicked.connect(lambda _checked=False, c=choice: self.pick(c))
            layout.addWidget(button)

    def pick(self, choice):
        self.choice = choice
        self.accept()
