"""Providers the user adds (any OpenAI-compatible API), shared by every
application using the sidecar. Each one has a name, an address, the model
filled in when it is chosen, its thinking capability and, optionally, how its
keys begin (a key pasted under the wrong provider is then refused). Keys are
never stored here: they stay in the OS vault like the built-in providers' keys.
"""
import json
import re
from pathlib import Path

BUILTIN = ('local', 'openai', 'anthropic', 'openrouter', 'groq', 'iteracompute', 'nvidia', 'mistral', 'compatible')
THINKING = ('unsupported', 'llama_cpp', 'reasoning_effort', 'anthropic_adaptive', 'anthropic_budget')


def path():
    from platformdirs import user_data_path
    return user_data_path('qtpy-ai-sidecar', appauthor=False) / 'providers.json'


def load():
    """[{key, label, base_url, model, thinking_backend, key_prefix}] of the user's providers."""
    try:
        value = json.loads(Path(path()).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    return [p for p in value if isinstance(p, dict) and p.get('key') and p.get('base_url')] if isinstance(value, list) else []


def find(key):
    return next((p for p in load() if p['key'] == key), None)


def keys():
    return [p['key'] for p in load()]


def make_key(label, taken=()):
    """'Z.ai direct' -> 'custom_z_ai_direct' (never a built-in name)."""
    base = 'custom_' + (re.sub(r'[^a-z0-9]+', '_', label.lower()).strip('_') or 'provider')
    key, n = base, 2
    while key in taken or key in BUILTIN:
        key, n = f'{base}_{n}', n + 1
    return key


def validate(entry):
    label = str(entry.get('label') or '').strip()
    url = str(entry.get('base_url') or '').strip()
    if not label:
        raise ValueError('Give the provider a name')
    if not url.startswith(('http://', 'https://')):
        raise ValueError('The API base URL must start with http:// or https:// (e.g. https://api.example.com/v1)')
    from .credentials import validate_endpoint
    validate_endpoint(url)
    if entry.get('thinking_backend', 'unsupported') not in THINKING:
        raise ValueError('Unknown thinking capability')


def save(entry):
    """Add the provider, or replace the one with the same key; returns its key."""
    validate(entry)
    providers = load()
    entry = {'key': entry.get('key') or make_key(entry['label'], [p['key'] for p in providers]),
             'label': entry['label'].strip(), 'base_url': entry['base_url'].strip().rstrip('/'),
             'model': str(entry.get('model') or '').strip(),
             'thinking_backend': entry.get('thinking_backend') or 'unsupported',
             'key_prefix': str(entry.get('key_prefix') or '').strip()}
    providers = [p for p in providers if p['key'] != entry['key']] + [entry]
    target = Path(path())
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(providers, indent=2), encoding='utf-8')
    return entry['key']


def remove(key):
    providers = [p for p in load() if p['key'] != key]
    target = Path(path())
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(providers, indent=2), encoding='utf-8')
