"""OS-vault-only credential storage. No file or plaintext fallback."""
import hashlib
import os
from urllib.parse import urlsplit

SERVICE = 'qtpy-ai-sidecar'
SECURE_MODULES = ('keyring.backends.Windows', 'keyring.backends.macOS',
                  'keyring.backends.SecretService', 'keyring.backends.libsecret', 'keyring.backends.kwallet')


def secure_backend():
    import keyring
    backend = keyring.get_keyring()
    if not type(backend).__module__.startswith(SECURE_MODULES):
        if type(backend).__module__ == 'keyring.backends.chainer':
            from keyring.backend import get_all_keyring
            secure = [b for b in get_all_keyring() if type(b).__module__.startswith(SECURE_MODULES) and b.priority > 0]
            if secure:
                return max(secure, key=lambda b: b.priority)
        # Reject fail/null/plaintext/chained third-party backends. The caller can
        # configure a native supported backend rather than downgrade protection.
        raise RuntimeError('No supported secure OS credential vault is selected. Plaintext storage is disabled.')
    return backend


def identity(config):
    value = config.provider + '\n' + config.base_url.rstrip('/')
    return hashlib.sha256(value.encode()).hexdigest()


def set_key(config, value):
    validate_endpoint(config.base_url)
    if not value.strip():
        raise ValueError('API key is empty')
    secure_backend().set_password(SERVICE, identity(config), value.strip())


def delete_key(config):
    backend = secure_backend()
    if backend.get_password(SERVICE, identity(config)):
        backend.delete_password(SERVICE, identity(config))


def get_key(config):
    validate_endpoint(config.base_url)
    if config.api_key_env:
        value = os.environ.get(config.api_key_env)
        if not value:
            raise ValueError('Missing credential environment variable: ' + config.api_key_env)
        return value
    if config.provider == 'local':
        return None
    if config.provider == 'compatible' and urlsplit(config.base_url).hostname in ('127.0.0.1', 'localhost', '::1'):
        try:
            return secure_backend().get_password(SERVICE, identity(config))
        except RuntimeError:
            return None  # Optional local-server auth; never falls back to file storage.
    value = secure_backend().get_password(SERVICE, identity(config))
    if not value:
        raise ValueError('No API key stored for this provider endpoint. Add it in Connection settings.')
    return value


def validate_endpoint(url):
    parsed = urlsplit(url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Do not put credentials or query parameters in model endpoint URLs')
    if parsed.scheme != 'https' and parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise ValueError('API credentials require HTTPS except for a local loopback server')
