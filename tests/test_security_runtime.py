import asyncio
import hashlib
import io
import json
import threading
import tarfile
import zipfile
import httpx
import pytest
from qtpy_ai_sidecar.config import Config
from qtpy_ai_sidecar import credentials, downloads
from qtpy_ai_sidecar.journal import Journal
from qtpy_ai_sidecar.runtime import OwnedLlama


def test_plaintext_vault_refused(monkeypatch):
    import keyring
    Unsafe = type('PlaintextKeyring', (), {'__module__': 'keyrings.alt.file'})
    monkeypatch.setattr(keyring, 'get_keyring', lambda: Unsafe())
    with pytest.raises(RuntimeError, match='Plaintext storage is disabled'):
        credentials.secure_backend()


def test_vault_store_read_delete_without_config_secret(monkeypatch, tmp_path):
    import keyring
    values = {}
    Secure = type('WinVaultKeyring', (), {'__module__': 'keyring.backends.Windows',
        'set_password': lambda s, service, ident, value: values.__setitem__((service, ident), value),
        'get_password': lambda s, service, ident: values.get((service, ident)),
        'delete_password': lambda s, service, ident: values.pop((service, ident))})
    monkeypatch.setattr(keyring, 'get_keyring', lambda: Secure())
    config = Config(provider='openai', base_url='https://api.openai.com/v1', state_dir=str(tmp_path))
    credentials.set_key(config, 'secret-123')
    assert credentials.get_key(config) == 'secret-123'
    config.save_connection()
    assert 'secret-123' not in (tmp_path / 'connection.json').read_text()
    credentials.delete_key(config)
    assert not values
    with pytest.raises(ValueError, match='No API key stored'):
        credentials.get_key(config)


def test_credentials_not_sent_over_plain_remote_http():
    with pytest.raises(ValueError, match='HTTPS'):
        Config(provider='openai', base_url='http://remote.example/v1')
    with pytest.raises(ValueError, match='credentials'):
        Config(provider='openai', base_url='https://key@api.example/v1')


def test_exact_secret_redacted_from_error(tmp_path):
    journal = Journal(tmp_path)
    journal.add_secret('private-example-key')
    journal.record('error', 'Provider echoed private-example-key')
    assert 'private-example-key' not in journal.path.read_text()


@pytest.mark.parametrize('system,machine,backend,suffix', [
    ('Windows','AMD64','vulkan','-bin-win-vulkan-x64.zip'),
    ('Windows','ARM64','cpu','-bin-win-cpu-arm64.zip'),
    ('Darwin','arm64','metal','-bin-macos-arm64.tar.gz'),
    ('Darwin','x86_64','cpu','-bin-macos-x64.tar.gz'),
    ('Linux','x86_64','vulkan','-bin-ubuntu-vulkan-x64.tar.gz'),
    ('Linux','aarch64','cpu','-bin-ubuntu-arm64.tar.gz')])
def test_portable_runtime_selection(system,machine,backend,suffix):
    assert downloads.asset_suffix(system,machine,backend) == suffix


def test_force_cpu_launch_arguments(monkeypatch,tmp_path):
    import qtpy_ai_sidecar.runtime as module
    executable, model = tmp_path/'llama-server', tmp_path/'test.gguf'
    executable.touch(); model.touch()
    seen = []
    class Process:
        def __init__(self, command, **kwargs): seen.extend(command)
        def poll(self): return None
        def terminate(self): pass
        def wait(self, **kwargs): pass
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def get(self,*args,**kwargs):
            return type('Response', (), {'status_code': 200})()
    monkeypatch.setattr(module.subprocess,'Popen',Process)
    monkeypatch.setattr(module.httpx,'AsyncClient',Client)
    config=Config(state_dir=str(tmp_path), runtime={'executable':str(executable),'model':str(model),'force_cpu':True,'gpu_layers':99})
    runtime=OwnedLlama(config)
    asyncio.run(runtime.ensure(threading.Event(), lambda *args:None))
    assert seen[seen.index('-ngl')+1] == '0'
    assert seen[seen.index('--device')+1] == 'none'
    assert '--no-op-offload' in seen and '--no-kv-offload' in seen
    runtime.stop()


def test_download_integrity_and_cancellation(monkeypatch,tmp_path):
    content=b'verified test model'
    original=httpx.Client
    monkeypatch.setattr(downloads.httpx,'Client',lambda **kw:original(**kw,transport=httpx.MockTransport(lambda req:httpx.Response(200,content=content))))
    destination=tmp_path/'test.gguf'
    downloads.download('https://test.invalid/model',destination,hashlib.sha256(content).hexdigest(),lambda *args:None,threading.Event())
    assert destination.read_bytes()==content
    with pytest.raises(ValueError,match='mismatch'):
        downloads.download('https://test.invalid/model',destination,'0'*64,lambda *args:None,threading.Event())
    assert destination.read_bytes()==content
    cancel=threading.Event(); cancel.set()
    with pytest.raises(InterruptedError):
        downloads.download('https://test.invalid/model',destination,hashlib.sha256(content).hexdigest(),lambda *args:None,cancel)
    assert not (tmp_path/'test.gguf.partial').exists()


def test_archive_traversal_refused(tmp_path):
    archive=tmp_path/'bad.zip'
    with zipfile.ZipFile(archive,'w') as out:out.writestr('../escape.txt','bad')
    with pytest.raises(ValueError,match='Unsafe'):
        downloads.extract_runtime(archive,tmp_path/'extract')
    assert not (tmp_path/'escape.txt').exists()


def test_unix_archive_permissions_and_executable(tmp_path):
    archive=tmp_path/'unix.tar.gz'
    with tarfile.open(archive,'w:gz') as out:
        member=tarfile.TarInfo('bin/llama-server');member.mode=0o755;member.size=5
        out.addfile(member,io.BytesIO(b'hello'))
    executable=downloads.extract_runtime(archive,tmp_path/'extract')
    assert executable.name=='llama-server' and executable.read_bytes()==b'hello'


def test_preferences_survive_provider_switch(tmp_path):
    config=Config(state_dir=str(tmp_path),provider='anthropic',base_url='https://api.anthropic.com/v1',thinking_backend='anthropic_adaptive',thinking='enabled')
    config.save_connection();config.save_performance()
    path=tmp_path/'app.json';path.write_text(json.dumps({'state_dir':str(tmp_path)}))
    loaded=Config.load(path)
    assert loaded.provider=='anthropic' and loaded.thinking=='enabled'
