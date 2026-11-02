from dataclasses import dataclass, field
from pathlib import Path
import json

# true of every model and every host: hosts may word it for their own risks
DEFAULT_NOTICE = 'Models can make mistakes. Check what they do.'


@dataclass
class Config:
    application: str = 'Application'
    model: str = 'local-model'
    base_url: str = 'http://127.0.0.1:1234/v1'
    api_key_env: str = ''
    context_tokens: int = 32768
    output_tokens: int = 8192
    max_steps: int = 32
    servers: dict = field(default_factory=dict)
    instructions: str = ''
    state_dir: str = ''
    adapter: dict = field(default_factory=dict)
    runtime: dict = field(default_factory=dict)
    thinking_backend: str = 'unsupported'
    thinking: str = 'default'
    thinking_strength: str = 'default'
    thinking_budget: int = -1
    provider: str = 'local'
    generation_timeout_seconds: int = 120
    response_timeout_s: int = 30  # Final-only recovery cap, owned by this model profile.
    compact_history: bool = True  # false: send every earlier tool result in full (the behaviour before 2026-10-27)
    # Compact history and searches once the payload fills this share of the context; 0 = always (default).
    # 0.5 was tried on 2026-10-27: Qwen 9B never crossed it yet was no faster, and Qwen3.5-4B did worse.
    compact_from: float = 0.0
    # the line always shown under the chat; empty = DEFAULT_NOTICE
    notice: str = ''
    # images returned by tools (figure previews) sent to the model: 'auto' when
    # the server reports a vision model, 'on', or 'off' (shown to the human only)
    vision: str = 'auto'

    def __post_init__(self):
        if not 512 <= self.output_tokens < self.context_tokens:
            raise ValueError('output_tokens must be >=512 and smaller than context_tokens')
        if not 10 <= self.generation_timeout_seconds <= 3600:
            raise ValueError('generation_timeout_seconds must be 10-3600')
        if isinstance(self.response_timeout_s, bool) or not isinstance(self.response_timeout_s, int) or not 10 <= self.response_timeout_s <= 3600:
            raise ValueError('response_timeout_s must be an integer from 10 to 3600')
        if self.vision not in ('auto', 'on', 'off'):
            raise ValueError("vision must be 'auto', 'on' or 'off'")
        if not 1 <= self.max_steps <= 50:
            raise ValueError('max_steps must be between 1 and 50')
        if not self.base_url.startswith(('http://', 'https://')):
            raise ValueError('base_url must be an HTTP(S) OpenAI-compatible endpoint')
        if self.thinking_backend not in ('unsupported', 'llama_cpp', 'reasoning_effort', 'anthropic_adaptive', 'anthropic_budget'):
            raise ValueError('Unknown thinking backend capability')
        if self.thinking not in ('default', 'enabled', 'disabled'):
            raise ValueError('Unknown thinking mode')
        if self.thinking_strength not in ('default', 'low', 'medium', 'high'):
            raise ValueError('Unknown thinking strength')
        if self.thinking_backend == 'unsupported' and (self.thinking != 'default' or self.thinking_strength != 'default'):
            raise ValueError('Configure a supported thinking backend before overriding thinking')
        if self.provider not in ('local', 'openai', 'anthropic', 'openrouter', 'compatible'):
            raise ValueError('Unknown model provider')
        if self.runtime and self.provider != 'local':
            raise ValueError('Owned runtimes are available only in local mode')
        from .credentials import validate_endpoint
        validate_endpoint(self.base_url)
        from urllib.parse import urlsplit
        if self.provider == 'local' and urlsplit(self.base_url).hostname not in ('127.0.0.1', 'localhost', '::1'):
            raise ValueError('Local mode requires a loopback endpoint; select a remote API provider explicitly')

    @classmethod
    def load(cls, path):
        value = json.loads(Path(path).read_text(encoding='utf-8'))
        value['servers'] = value.pop('mcpServers', value.get('servers', {}))
        config = cls(**value)
        preferences = config.storage() / 'performance.json'
        if preferences.exists():
            saved = json.loads(preferences.read_text(encoding='utf-8'))
            for key in ('context_tokens', 'output_tokens', 'thinking', 'thinking_strength', 'thinking_budget', 'generation_timeout_seconds', 'max_steps', 'vision'):
                if key in saved:
                    setattr(config, key, saved[key])
            if config.runtime:
                config.runtime = {**config.runtime, **{k: saved[k] for k in ('gpu_layers', 'threads', 'force_cpu') if k in saved}}
        connection = config.storage() / 'connection.json'
        if connection.exists():
            saved = json.loads(connection.read_text(encoding='utf-8'))
            for key in ('provider', 'model', 'base_url', 'api_key_env', 'thinking_backend', 'runtime'):
                if key in saved:
                    setattr(config, key, saved[key])
        config.__post_init__()
        servers = config.storage() / 'servers.json'
        if servers.exists():
            config.servers = json.loads(servers.read_text(encoding='utf-8'))
        return config

    def import_servers(self, path):
        import re
        value = json.loads(Path(path).read_text(encoding='utf-8'))
        servers = value.get('mcpServers', value.get('servers'))
        if not isinstance(servers, dict):
            raise ValueError('Select a JSON file with an mcpServers object')
        for server in servers.values():
            if not isinstance(server, dict) or not any(k in server for k in ('command', 'url')):
                raise ValueError('Each MCP server needs a command or URL')
            for section in ('headers', 'env'):
                for name, item in server.get(section, {}).items():
                    if re.search(r'authorization|api.?key|token|secret|password', name, re.I) and not re.search(r'\$\{\w+\}|%\w+%', str(item)):
                        raise ValueError('MCP credentials must reference environment variables; secret literals are not imported')
        self.storage().mkdir(parents=True, exist_ok=True)
        (self.storage() / 'servers.json').write_text(json.dumps(servers, indent=2), encoding='utf-8')
        self.servers = servers

    def save_connection(self):
        value = {k: getattr(self, k) for k in ('provider', 'model', 'base_url', 'api_key_env', 'thinking_backend', 'runtime')}
        self.storage().mkdir(parents=True, exist_ok=True)
        (self.storage() / 'connection.json').write_text(json.dumps(value, indent=2), encoding='utf-8')

    def save_performance(self):
        value = {k: getattr(self, k) for k in ('context_tokens', 'output_tokens', 'thinking', 'thinking_strength', 'thinking_budget', 'generation_timeout_seconds', 'max_steps', 'vision')}
        value.update({k: self.runtime[k] for k in ('gpu_layers', 'threads', 'force_cpu') if k in self.runtime})
        self.storage().mkdir(parents=True, exist_ok=True)
        (self.storage() / 'performance.json').write_text(json.dumps(value, indent=2), encoding='utf-8')

    def storage(self):
        if self.state_dir:
            return Path(self.state_dir).expanduser().resolve()
        from platformdirs import user_data_path
        import re
        name = re.sub(r'[^a-zA-Z0-9_-]', '_', self.application)
        return user_data_path('qtpy-ai-sidecar', appauthor=False) / name
