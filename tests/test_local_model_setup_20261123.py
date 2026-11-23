"""User 2026-11-23: "all of this is hard, can't it be automated" / "if not present it should
download it and please make it simpler to use for end user". The local model is found on this
computer (the sidecar's downloads, LM Studio, the Hugging Face cache) or downloaded, in one step.
No network: the downloads are fakes."""
from pathlib import Path

import pytest

from qtpy_ai_sidecar import discover, downloads, hardware
from qtpy_ai_sidecar.config import Config

Q27 = 'lmstudio-community/Qwen3.8-27B-GGUF'
Q9 = 'lmstudio-community/Qwen3.5-9B-GGUF'
BACKENDS = Path('C:/u/.lmstudio/extensions/backends')


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'')
    return path


def test_models_found_skip_vision_projectors_and_split_sets(tmp_path):
    keep = _touch(tmp_path / 'lmstudio-community' / 'Qwen3.8-27B-GGUF' / 'Qwen3.8-27B-Q4_K_M.gguf')
    _touch(tmp_path / 'lmstudio-community' / 'Qwen3.8-27B-GGUF' / 'mmproj-Qwen3.8-27B-BF16.gguf')
    _touch(tmp_path / 'big' / 'Big-Q4_K_M-00001-of-00002.gguf')
    assert discover.find_models([tmp_path]) == [keep]


def test_the_recommended_model_or_a_smaller_one_never_a_larger_one():
    paths = [Path('m/Qwen3.8-27B-Q8_0.gguf'), Path('m/Qwen3.8-27B-Q4_K_M.gguf'), Path('m/Qwen3.5-9B-Q4_K_M.gguf')]
    assert discover.pick_model(paths, Q27).name == 'Qwen3.8-27B-Q4_K_M.gguf'
    assert discover.pick_model(paths, Q9).name == 'Qwen3.5-9B-Q4_K_M.gguf'        # 27B would not fit
    assert discover.pick_model(paths[:2], Q9) is None
    assert discover.pick_model([Path('m/Qwen3.5-9B-Q4_K_M.gguf')], Q27).name == 'Qwen3.5-9B-Q4_K_M.gguf'


def test_the_newest_llama_server_of_the_best_kind():
    exe = 'llama-server.exe'
    paths = [BACKENDS / 'llama.cpp-win-x86_64-nvidia-cuda-avx2-2.62.1' / exe,
             BACKENDS / 'llama.cpp-win-x86_64-nvidia-cuda12-avx2-2.69.0' / exe,
             BACKENDS / 'llama.cpp-win-x86_64-nvidia-cuda12-avx2-2.9.0' / exe,
             BACKENDS / 'llama.cpp-win-x86_64-vulkan-avx2-2.70.0' / exe,
             BACKENDS / 'llama.cpp-win-x86_64-avx2-cpu-2.71.0' / exe]
    assert discover.pick_runtime(paths, gpu_gib=24).parent.name.endswith('cuda12-avx2-2.69.0')
    assert 'vulkan' in discover.pick_runtime(paths, gpu_gib=None).parent.name
    assert 'cpu' in discover.pick_runtime(paths[-1:], gpu_gib=24).parent.name
    assert discover.pick_runtime([], gpu_gib=24) is None


def _computer(monkeypatch, tmp_path, model=True, runtime=True, gpu=24):
    models, backends = tmp_path / 'lmstudio' / 'models', tmp_path / 'lmstudio' / 'backends'
    models.mkdir(parents=True)
    backends.mkdir(parents=True)
    if model:
        _touch(models / 'lmstudio-community' / 'Qwen3.8-27B-GGUF' / 'Qwen3.8-27B-Q4_K_M.gguf')
    if runtime:
        _touch(backends / 'llama.cpp-win-x86_64-nvidia-cuda12-avx2-2.69.0' / 'llama-server.exe')
    monkeypatch.setattr(discover, 'model_folders', lambda storage=None: [models, Path(storage) / 'models'])
    monkeypatch.setattr(discover, 'runtime_folders', lambda storage=None: [backends, Path(storage) / 'runtimes'])
    monkeypatch.setattr(discover.shutil, 'which', lambda name: None)
    monkeypatch.setattr(discover.platform, 'system', lambda: 'Windows')
    monkeypatch.setattr(hardware, 'apple_silicon', lambda: False)
    monkeypatch.setattr(hardware, 'gpu_memory_gib', lambda: gpu)


def test_found_on_this_computer_is_used_with_no_download(tmp_path, monkeypatch):
    _computer(monkeypatch, tmp_path)
    monkeypatch.setattr(downloads, 'model_files', lambda repo: pytest.fail('no download expected'))
    config = Config(application='Demo', state_dir=str(tmp_path / 'state'))
    message = discover.setup(config, download=False)
    assert config.provider == 'local' and config.runtime['model'].endswith('Qwen3.8-27B-Q4_K_M.gguf')
    assert 'cuda12' in config.runtime['executable'] and config.runtime['gpu_layers'] == 99
    assert config.context_tokens == 65536                      # the 27B model's tested context
    assert 'found in the sidecar folder' not in message and 'Qwen3.8-27B-Q4_K_M.gguf found' in message


def test_nothing_found_without_download_says_so(tmp_path, monkeypatch):
    _computer(monkeypatch, tmp_path, model=False)
    with pytest.raises(LookupError):
        discover.setup(Config(application='Demo', state_dir=str(tmp_path / 'state')), download=False)


def test_nothing_found_downloads_the_recommended_model_and_llama_cpp(tmp_path, monkeypatch):
    _computer(monkeypatch, tmp_path, model=False, runtime=False)
    got = []
    files = [{'repository': Q27, 'revision': 'a' * 40, 'name': n, 'size': s, 'sha256': 'x'}
             for n, s in (('Qwen3.8-27B-Q8_0.gguf', 28), ('Qwen3.8-27B-Q4_K_M.gguf', 17),
                          ('mmproj-Qwen3.8-27B-F16.gguf', 2), ('mmproj-Qwen3.8-27B-BF16.gguf', 1))]
    monkeypatch.setattr(downloads, 'model_files', lambda repo: got.append(repo) or files)
    monkeypatch.setattr(downloads, 'download_model', lambda item, root, emit, cancel: got.append(item['name'])
                        or Path(root) / 'models' / item['name'])
    monkeypatch.setattr(downloads, 'check_runtime', lambda backend: got.append(backend) or {'backend': backend})
    monkeypatch.setattr(downloads, 'install_runtime', lambda item, root, emit, cancel: Path(root) / 'runtimes' / 'b1-vulkan' / 'llama-server.exe')
    config = Config(application='Demo', state_dir=str(tmp_path / 'state'))
    message = discover.setup(config)
    assert got == [Q27, 'Qwen3.8-27B-Q4_K_M.gguf', 'mmproj-Qwen3.8-27B-BF16.gguf', 'vulkan']
    assert config.runtime['model'].endswith('Qwen3.8-27B-Q4_K_M.gguf') and 'downloaded' in message
    assert 'installed llama.cpp' in message


def test_ollama_models_are_found_through_their_manifests(tmp_path, monkeypatch):
    root = tmp_path / 'ollama'
    _touch(root / 'blobs' / 'sha256-abc').write_bytes(b'GGUF' * 10)
    manifest = _touch(root / 'manifests' / 'registry.ollama.ai' / 'library' / 'qwen3.8' / '27b')
    manifest.write_text('{"layers": [{"mediaType": "application/vnd.ollama.image.license", "digest": "sha256:zz"},'
                        ' {"mediaType": "application/vnd.ollama.image.model", "digest": "sha256:abc"}]}')
    monkeypatch.setenv('OLLAMA_MODELS', str(root))
    assert discover.ollama_models() == [('qwen3.8:27b', root / 'blobs' / 'sha256-abc')]
    models = discover.local_models()
    assert [(m['name'], m['source']) for m in models] == [('qwen3.8:27b', 'Ollama')]
    assert discover.pick_model(models, Q27) == root / 'blobs' / 'sha256-abc'       # qwen3.8:27b is Qwen3.8 27B


def test_lm_studio_custom_models_folder_is_searched(tmp_path):
    home = discover.HOME                                           # the tests' empty home
    custom = tmp_path / 'D_models'
    _touch(custom / 'lmstudio-community' / 'Qwen3.5-9B-GGUF' / 'Qwen3.5-9B-Q4_K_M.gguf')
    _touch(home / '.lmstudio' / 'settings.json').write_text('{"downloadsFolder": "%s"}' % custom.as_posix())
    models = discover.local_models()
    assert [m['name'] for m in models] == ['Qwen3.5-9B-Q4_K_M'] and models[0]['source'] == 'LM Studio'
    assert custom in models[0]['path'].parents


def test_the_dialog_lists_the_models_on_this_computer_and_uses_the_chosen_one(monkeypatch, tmp_path):
    from qtpy_ai_sidecar import library
    a, b = tmp_path / 'Qwen3.5-9B-Q4_K_M.gguf', tmp_path / 'Other-7B.gguf'
    monkeypatch.setattr(hardware, 'recommend_for_this_computer', lambda: (Q9, 'Qwen3.5 9B'))
    monkeypatch.setattr(discover, 'local_models', lambda storage=None: [
        {'name': 'Other-7B', 'path': b, 'source': 'Ollama', 'gb': 9.0},
        {'name': 'Qwen3.5-9B-Q4_K_M', 'path': a, 'source': 'LM Studio', 'gb': 5.4}])
    used = []
    monkeypatch.setattr(discover, 'setup', lambda config, emit=None, cancel=None, download=True, model=None:
                        used.append(model) or 'Local model set up.')
    dialog = library.LibraryDialog(Config(application='Demo', state_dir=str(tmp_path)))
    assert dialog.found.count() == 2 and 'LM Studio' in dialog.found.currentText()     # the recommended one
    monkeypatch.setattr(dialog, 'run', lambda kind, action: dialog.receive('error', action()))
    dialog.use_found_model()
    assert used == [a]
    dialog.deleteLater()


def test_no_model_on_this_computer_says_so(tmp_path):
    from qtpy_ai_sidecar import library
    dialog = library.LibraryDialog(Config(application='Demo', state_dir=str(tmp_path)))
    assert dialog.found.currentText() == 'No model found on this computer' and not dialog.use_found.isEnabled()
    dialog.deleteLater()


def test_the_dialog_is_one_button_with_the_rest_under_advanced(monkeypatch, tmp_path):
    from qtpy_ai_sidecar import library
    monkeypatch.setattr(hardware, 'recommend_for_this_computer', lambda: (Q27, 'Qwen3.8 27B (this computer: 24 GB)'))
    saved = []
    config = Config(application='Demo', state_dir=str(tmp_path))
    monkeypatch.setattr(config, 'save_connection', lambda: saved.append('c'))
    monkeypatch.setattr(config, 'save_performance', lambda: saved.append('p'))
    dialog = library.LibraryDialog(config)
    assert dialog.auto_button.text() == 'Set up automatically' and dialog.advanced.isHidden()
    dialog.toggle_advanced()
    assert not dialog.advanced.isHidden()
    dialog.receive('auto_ready', 'Local model set up: x.')
    assert saved == ['c', 'p'] and 'send your message' in dialog.status.text()
    dialog.deleteLater()


@pytest.mark.real_setup
def test_sending_with_no_model_sets_it_up_then_sends(tmp_path, monkeypatch):
    from qtpy_ai_sidecar.widgets import AssistantDock

    def found(config, download=True):
        discover.apply(config, tmp_path / 'Qwen3.8-27B-Q4_K_M.gguf', tmp_path / 'llama-server.exe')
        return 'Local model set up: Qwen3.8-27B-Q4_K_M.gguf found in LM Studio.'
    monkeypatch.setattr(discover, 'setup', found)
    monkeypatch.setattr(Config, 'save_connection', lambda self: None)
    monkeypatch.setattr(Config, 'save_performance', lambda self: None)
    dock = AssistantDock(Config(application='Demo', state_dir=str(tmp_path)))
    assert dock.local_model_ready()
    assert dock.engine.config.runtime['model'].endswith('Qwen3.8-27B-Q4_K_M.gguf')
    dock.close()
    dock.deleteLater()


@pytest.mark.real_setup
def test_nothing_found_and_the_offer_closed_keeps_the_text(tmp_path, monkeypatch):
    from qtpy_ai_sidecar import widgets

    def missing(config, download=True):
        raise LookupError('No local model found on this computer.')
    monkeypatch.setattr(discover, 'setup', missing)
    monkeypatch.setattr(hardware, 'recommend_for_this_computer', lambda: (Q27, ''))
    offered = []
    monkeypatch.setattr(widgets.QMessageBox, 'exec', lambda box: offered.append(box.text()) or 0)
    dock = widgets.AssistantDock(Config(application='Demo', state_dir=str(tmp_path)))
    dock.input.setPlainText('Make the letters bold')
    dock.send()
    assert offered and 'about 18 GB' in offered[0] and 'downloaded once' in offered[0]
    assert dock.input.toPlainText() == 'Make the letters bold' and 'no model' in dock.status.text()
    dock.close()
    dock.deleteLater()


def test_one_model_button_asks_where_first(tmp_path, monkeypatch):
    from qtpy_ai_sidecar import widgets
    from qtpy_ai_sidecar.model_choice import ModelChoice
    dialog = ModelChoice(Config(application='Demo', state_dir=str(tmp_path)))
    assert 'no model set up yet' in dialog.findChildren(widgets.QLabel)[0].text()
    dialog.local_button.click()
    assert dialog.choice == 'local'
    dialog.deleteLater()
    dock = widgets.AssistantDock(Config(application='Demo', state_dir=str(tmp_path)))
    assert dock.connection_button.text() == 'Model' and dock.library_button.isHidden()
    opened = []
    for choice in ('local', 'online', None):
        monkeypatch.setattr(ModelChoice, 'exec', lambda self, c=choice: setattr(self, 'choice', c) or 0)
        monkeypatch.setattr(dock, 'library', lambda auto=False: opened.append('library'))
        monkeypatch.setattr(dock, 'connection_settings', lambda online=False: opened.append(('online', online)))
        dock.choose_model()
    assert opened == ['library', ('online', True)]
    dock.close()
    dock.deleteLater()


def test_the_online_window_has_no_local_entry_and_starts_on_a_provider(tmp_path):
    from qtpy_ai_sidecar.connection import ConnectionDialog
    dialog = ConnectionDialog(Config(application='Demo', state_dir=str(tmp_path)), online=True)
    keys = [dialog.provider.itemData(i) for i in range(dialog.provider.count())]
    assert 'local' not in keys and dialog.provider.currentData() == 'mistral'
    assert 'mistral' in dialog.url.text()
    dialog.deleteLater()


def test_hugging_face_cache_moved_by_hf_home(tmp_path, monkeypatch):
    monkeypatch.setenv('HF_HOME', str(tmp_path / 'hf'))
    monkeypatch.delenv('HF_HUB_CACHE', raising=False)
    assert discover.huggingface_folder() == tmp_path / 'hf' / 'hub'
    _touch(tmp_path / 'hf' / 'hub' / 'models--x--Qwen3.5-4B-GGUF' / 'snapshots' / 'abc' / 'Qwen3.5-4B-Q4_K_M.gguf')
    assert [m['source'] for m in discover.local_models()] == ['the Hugging Face cache']
