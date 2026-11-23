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
    monkeypatch.setattr(discover, 'works', lambda exe: (True, ''))       # the fake llama-server "starts"


def test_found_on_this_computer_is_used_with_no_download(tmp_path, monkeypatch):
    _computer(monkeypatch, tmp_path)
    monkeypatch.setattr(downloads, 'model_files', lambda repo: pytest.fail('no download expected'))
    # coming from Mistral (chat 2026-11-23: its 200,000-token context and name were kept)
    config = Config(application='Demo', state_dir=str(tmp_path / 'state'), context_tokens=200000,
                    model='mistral-large-4')
    message = discover.setup(config, download=False)
    assert config.provider == 'local' and config.runtime['model'].endswith('Qwen3.8-27B-Q4_K_M.gguf')
    assert 'cuda12' in config.runtime['executable'] and config.runtime['gpu_layers'] == 99
    assert config.context_tokens == 65536                      # the 27B model's tested context
    assert config.model == 'Qwen3.8-27B-Q4_K_M' and config.output_tokens < config.context_tokens
    assert 'Qwen3.8-27B-Q4_K_M found in LM Studio' in message and 'llama.cpp (cuda) found in LM Studio' in message


def test_a_llama_server_that_does_not_start_is_skipped_then_the_official_one_offered(tmp_path, monkeypatch):
    _computer(monkeypatch, tmp_path)
    monkeypatch.setattr(discover, 'works', lambda exe: (False, 'exit code 3221225781, no message (a missing library?)'))
    p = discover.plan(Config(application='Demo', state_dir=str(tmp_path / 'state')))
    assert p['executable'] is None and p['download_runtime'] == 'vulkan' and not p['download_model']
    assert 'missing library' in p['problems'][0]
    text = discover.download_text(p)
    assert 'llama.cpp' in text and 'github.com' in text and 'Hugging Face' not in text


def test_ollama_only_computer(tmp_path, monkeypatch):
    """User 2026-11-23: 'if LM Studio is not there but Ollama is make sure it also works'."""
    _computer(monkeypatch, tmp_path, model=False, runtime=False)
    root = tmp_path / 'ollama'
    _touch(root / 'blobs' / 'sha256-abc').write_bytes(b'GGUF' + b'\0' * 60)
    _touch(root / 'manifests' / 'registry.ollama.ai' / 'library' / 'qwen3.8' / '27b').write_text(
        '{"layers": [{"mediaType": "application/vnd.ollama.image.model", "digest": "sha256:abc"}]}')
    monkeypatch.setenv('OLLAMA_MODELS', str(root))
    p = discover.plan(Config(application='Demo', state_dir=str(tmp_path / 'state')))
    assert p['model'] == root / 'blobs' / 'sha256-abc' and p['name'] == 'qwen3.8:27b'
    assert p['download_runtime'] == 'vulkan' and not p['download_model']    # Ollama ships no llama-server
    monkeypatch.setattr(downloads, 'check_runtime', lambda backend: {'tag': 'b1', 'backend': backend})
    monkeypatch.setattr(downloads, 'install_runtime', lambda item, root_, emit, cancel: tmp_path / 'rt' / 'llama-server.exe')
    config = Config(application='Demo', state_dir=str(tmp_path / 'state'))
    steps = []
    message = discover.run_plan(config, p, say=steps.append)
    assert config.runtime['model'].endswith('sha256-abc') and config.runtime['model_name'] == 'qwen3.8:27b'
    assert config.context_tokens == 65536 and 'qwen3.8:27b found in Ollama' in message
    assert any('Downloading llama.cpp' in s for s in steps)
    from qtpy_ai_sidecar.model_choice import running
    assert running(config) == 'On this computer · qwen3.8:27b'


def test_the_runtime_accepts_an_ollama_blob_and_explains_a_crash(tmp_path):
    from qtpy_ai_sidecar.runtime import OwnedLlama
    log = tmp_path / 'llama-server.log'
    log.write_text('')
    llama = OwnedLlama(Config(application='Demo', state_dir=str(tmp_path)))
    llama.log = log.open('a', encoding='utf-8')
    assert 'could not start (a missing library?)' in llama.exit_reason(log)
    log.write_text('load_tensors: loading\nggml_backend_cuda_buffer_type_alloc_buffer: allocating 17000 MiB: cudaMalloc failed: out of memory\n')
    reason = llama.exit_reason(log)
    assert 'does not fit in the graphics memory' in reason and 'out of memory' in reason and 'Model button' in reason
    llama.log.close()
    blob = tmp_path / 'sha256-abc'
    blob.write_bytes(b'GGUF1234')
    assert discover.is_gguf(blob) and not discover.is_gguf(log)


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


def test_lm_studio_llama_server_gets_its_vendor_libraries(tmp_path, monkeypatch):
    """User 2026-11-23: 'Owned llama.cpp exited', empty log: LM Studio's CUDA llama-server needs
    backends/vendor/win-llama-cuda12-vendor-v2 on its library path."""
    backends = tmp_path / 'backends'
    exe = _touch(backends / 'llama.cpp-win-x86_64-nvidia-cuda12-avx2-2.69.0' / 'llama-server.exe')
    (exe.parent / 'backend-manifest.json').write_text('{"vendor_lib_package_names": ["win-llama-cuda12-vendor-v2"]}')
    broken = _touch(backends / 'llama.cpp-win-x86_64-nvidia-cuda12-avx2-2.70.0' / 'llama-server.exe')
    (broken.parent / 'backend-manifest.json').write_text('{"vendor_lib_package_names": ["missing-vendor"]}')
    vendor = backends / 'vendor' / 'win-llama-cuda12-vendor-v2'
    vendor.mkdir(parents=True)
    monkeypatch.setattr(discover.platform, 'system', lambda: 'Windows')
    env = discover.runtime_environment(exe, {'PATH': 'C:/Windows'})
    assert env['PATH'].split(discover.os.pathsep) == [str(vendor), 'C:/Windows']
    assert discover.pick_runtime([exe, broken], gpu_gib=24) == exe          # newer, but its libraries are missing
    assert discover.runtime_environment(tmp_path / 'llama-server.exe', {'PATH': 'x'}) == {'PATH': 'x'}


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
    monkeypatch.setattr(discover, 'plan', lambda config, model=None, name=None, say=None:
                        used.append((model, name)) or {'download_model': None, 'download_runtime': None, 'problems': []})
    monkeypatch.setattr(discover, 'run_plan', lambda config, p, emit=None, cancel=None, say=None:
                        used.append('run') or 'Local model set up.')
    asked = []
    from qtpy.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox,
                        'question', lambda *a, **k: asked.append(a) or 0)
    dialog = library.LibraryDialog(Config(application='Demo', state_dir=str(tmp_path)))
    assert dialog.found.count() == 2 and 'LM Studio' in dialog.found.currentText()     # the recommended one
    _synchronous(dialog, monkeypatch)
    dialog.use_found_model()
    assert used == [(a, 'Qwen3.5-9B-Q4_K_M'), 'run'] and not asked                   # nothing to download: no question
    dialog.deleteLater()


def _synchronous(dialog, monkeypatch):
    """The dialog's worker thread, run in place (as the signals would deliver it)."""
    def run(kind, action):
        dialog.busy = True
        try:
            dialog.receive(kind, action())
        except Exception as exc:
            dialog.receive('error', str(exc))
        dialog.receive('finished', None)
    monkeypatch.setattr(dialog, 'run', run)


def test_downloads_are_listed_and_need_a_yes(monkeypatch, tmp_path):
    """User 2026-11-23: 'inform the user you gonna download things from internet of course before
    hand' / 'offer download of llama and model with progress bars'."""
    from qtpy.QtWidgets import QMessageBox
    from qtpy_ai_sidecar import library
    plan = {'model': None, 'name': None, 'executable': None, 'download_model': Q27, 'download_runtime': 'vulkan',
            'notes': [], 'why': '', 'problems': []}
    monkeypatch.setattr(discover, 'plan', lambda config, model=None, name=None, say=None: plan)
    ran = []
    monkeypatch.setattr(discover, 'run_plan', lambda config, p, emit=None, cancel=None, say=None: ran.append(p) or 'ok')
    asked, answer = [], [QMessageBox.StandardButton.No]
    monkeypatch.setattr(QMessageBox, 'question', lambda parent, title, text, *a: asked.append(text) or answer[0])
    dialog = library.LibraryDialog(Config(application='Demo', state_dir=str(tmp_path)))
    _synchronous(dialog, monkeypatch)
    dialog.set_up_automatically()
    assert 'download from the internet' in asked[0] and 'about 18 GB' in asked[0] and 'huggingface.co' in asked[0]
    assert 'github.com/ggml-org/llama.cpp' in asked[0]
    assert not ran and 'Nothing downloaded' in dialog.status.text()
    answer[0] = QMessageBox.StandardButton.Yes
    dialog.set_up_automatically()
    assert ran == [plan]
    dialog.deleteLater()


def test_a_download_shows_its_step_and_progress_and_a_failure_is_said(monkeypatch, tmp_path):
    from qtpy.QtWidgets import QMessageBox
    from qtpy_ai_sidecar import library
    dialog = library.LibraryDialog(Config(application='Demo', state_dir=str(tmp_path)))
    dialog.receive('say', 'Downloading the model Qwen3.8-27B-Q4_K_M.gguf (15.7 GB)…')
    dialog.receive('progress', {'total': 1000 * 2**20, 'downloaded': 250 * 2**20})
    assert dialog.progress.value() == 25 and 'Qwen3.8-27B-Q4_K_M.gguf' in dialog.status.text()
    assert '25 %' in dialog.status.text()
    warned = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda parent, title, text, *a: warned.append(text))
    dialog.receive('error', 'Could not reach Hugging Face to download the model (timeout).')
    dialog.receive('finished', None)
    assert warned and 'Could not reach Hugging Face' in warned[0] and 'online service' in warned[0]
    assert dialog.status.text().startswith('Failed:') and dialog.progress.maximum() == 100
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
    assert saved == ['c', 'p'] and dialog.progress.value() == 100
    assert dialog.result() == library.QDialog.DialogCode.Accepted        # closes itself when done
    dialog.deleteLater()


@pytest.mark.real_setup
def test_sending_with_no_model_sets_it_up_then_sends(tmp_path, monkeypatch):
    from qtpy_ai_sidecar.widgets import AssistantDock

    def found(config, p, emit=None, cancel=None, say=None):
        discover.apply(config, tmp_path / 'Qwen3.8-27B-Q4_K_M.gguf', tmp_path / 'llama-server.exe')
        return 'Local model set up: Qwen3.8-27B-Q4_K_M found in LM Studio.'
    monkeypatch.setattr(discover, 'plan', lambda config: {'download_model': None, 'download_runtime': None})
    monkeypatch.setattr(discover, 'run_plan', found)
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

    monkeypatch.setattr(discover, 'plan', lambda config: {'download_model': Q27, 'download_runtime': 'vulkan'})
    monkeypatch.setattr(discover, 'run_plan', lambda *a, **k: pytest.fail('nothing runs before the yes'))
    offered = []
    monkeypatch.setattr(widgets.QMessageBox, 'exec', lambda box: offered.append(box.text()) or 0)
    dock = widgets.AssistantDock(Config(application='Demo', state_dir=str(tmp_path)))
    dock.input.setPlainText('Make the letters bold')
    dock.send()
    assert offered and 'download from the internet, once' in offered[0] and 'about 18 GB' in offered[0]
    assert 'huggingface.co' in offered[0] and 'github.com' in offered[0]
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
