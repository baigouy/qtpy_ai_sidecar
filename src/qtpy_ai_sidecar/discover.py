"""Set up the local model by itself (user 2026-11-23: "all of this is hard, can't it be
automated" / "search LM Studio default folder and or Ollama for models ... so that if the user
already has some models on his computer he can easily reuse them"): list the GGUF models and
llama-server builds already on this computer (the sidecar's own downloads, LM Studio, Ollama,
the Hugging Face cache), pick the ones this computer runs best, and when none is there,
download the recommended model and the official llama.cpp runtime."""
import json
import os
import platform
import re
import shutil
from pathlib import Path

from . import hardware

HOME = Path.home()


def lmstudio_folders():
    """LM Studio's model folders: its default ones and the one chosen in its settings."""
    folders = [HOME / '.lmstudio' / 'models', HOME / '.cache' / 'lm-studio' / 'models']
    try:
        chosen = json.loads((HOME / '.lmstudio' / 'settings.json').read_text(encoding='utf-8')).get('downloadsFolder')
        if chosen:
            folders.insert(0, Path(chosen))
    except (OSError, ValueError, AttributeError):
        pass
    return folders


def huggingface_folder():
    """The Hugging Face hub cache (same place on Windows, macOS and Linux unless moved)."""
    if os.environ.get('HF_HUB_CACHE'):
        return Path(os.environ['HF_HUB_CACHE'])
    if os.environ.get('HF_HOME'):
        return Path(os.environ['HF_HOME']) / 'hub'
    return HOME / '.cache' / 'huggingface' / 'hub'


def model_folders(storage=None):
    folders = [Path(storage) / 'models'] if storage else []
    folders += lmstudio_folders() + [huggingface_folder()]
    unique = []
    for f in folders:
        if f.is_dir() and f not in unique:
            unique.append(f)
    return unique


def runtime_folders(storage=None):
    folders = [Path(storage) / 'runtimes'] if storage else []
    folders += [HOME / '.lmstudio' / 'extensions' / 'backends',
                HOME / '.cache' / 'lm-studio' / 'extensions' / 'backends']
    return [f for f in folders if f.is_dir()]


def ollama_folders():
    """Ollama's model folders: OLLAMA_MODELS, else ~/.ollama/models (Windows, macOS, Linux user
    install) and the Linux service install's /usr/share/ollama/.ollama/models."""
    if os.environ.get('OLLAMA_MODELS'):
        return [Path(os.environ['OLLAMA_MODELS'])]
    folders = [HOME / '.ollama' / 'models']
    if platform.system() == 'Linux':
        folders.append(Path('/usr/share/ollama/.ollama/models'))
    return folders


def ollama_models(root=None):
    """(name, path) of Ollama's models: its manifests name the blob holding each GGUF."""
    found = []
    for folder in ([Path(root)] if root else ollama_folders()):
        found += _ollama_models(folder)
    return found


def _ollama_models(root):
    manifests = root / 'manifests'
    found = []
    try:
        if not manifests.is_dir():
            return found
    except OSError:                       # a folder this user may not read
        return found
    for here, _dirs, files in os.walk(manifests):
        for tag in files:
            path = Path(here) / tag
            try:
                layers = json.loads(path.read_text(encoding='utf-8')).get('layers', [])
            except (OSError, ValueError, AttributeError):
                continue
            for layer in layers:
                if layer.get('mediaType') == 'application/vnd.ollama.image.model':
                    blob = root / 'blobs' / str(layer.get('digest', '')).replace(':', '-')
                    if blob.is_file():
                        found.append((path.parent.name + ':' + tag, blob))
    return found


def _walk(folders, match, depth=6):
    """Files under the folders whose name matches; links are followed (the Hugging Face cache
    keeps its files as links), at most `depth` levels down."""
    found = []
    for root in folders:
        base = len(Path(root).parts)
        for here, dirs, files in os.walk(root, followlinks=True):
            if len(Path(here).parts) - base >= depth:
                dirs[:] = []
            found += [Path(here) / f for f in files if match(f)]
    return found


def find_models(folders):
    """Single-file GGUF models (not vision projectors, not split sets)."""
    return _walk(folders, lambda f: f.lower().endswith('.gguf') and not f.lower().startswith('mmproj')
                 and not re.search(r'-\d{5}-of-\d{5}\.gguf$', f, re.I))


def find_runtimes(folders):
    """llama-server builds: in the folders, on PATH, and where Homebrew / Linux packages put it
    (apps started from the macOS Finder do not get the shell's PATH)."""
    windows = platform.system() == 'Windows'
    name = 'llama-server.exe' if windows else 'llama-server'
    found = _walk(folders, lambda f: f == name)
    on_path = shutil.which('llama-server')
    found += [Path(on_path)] if on_path else []
    if not windows:
        found += [p for p in (Path('/opt/homebrew/bin/llama-server'), Path('/usr/local/bin/llama-server'),
                              Path('/usr/bin/llama-server')) if p.is_file()]
        found = [p for p in found if os.access(p, os.X_OK)]
    unique = []
    for p in found:
        if p not in unique:
            unique.append(p)
    return unique


def where(path):
    text = str(path).lower().replace('\\', '/')
    if '.ollama' in text or '/blobs/sha256-' in text:
        return 'Ollama'
    if 'lmstudio' in text or 'lm-studio' in text:
        return 'LM Studio'
    if 'huggingface' in text or ('/models--' in text and '/snapshots/' in text):
        return 'the Hugging Face cache'
    return 'the sidecar folder'


def local_models(storage=None):
    """Every model on this computer, as {'name', 'path', 'source', 'gb'}, largest first."""
    items = [(p.stem, p) for p in find_models(model_folders(storage))] + ollama_models()
    seen, out = set(), []
    for name, path in items:
        if path in seen:
            continue
        seen.add(path)
        try:
            gb = path.stat().st_size / 1024**3
        except OSError:
            continue
        out.append({'name': name, 'path': path, 'source': where(path), 'gb': gb})
    return sorted(out, key=lambda m: -m['gb'])


def _short(repo):
    return repo.split('/')[-1].replace('-GGUF', '').lower()


def _named(item):
    """(name, path) of a Path, a (name, path) pair or a local_models entry."""
    if isinstance(item, dict):
        return item['name'], item['path']
    if isinstance(item, tuple):
        return item
    return item.name, item


def pick_model(items, recommended):
    """The recommended model, else the next smaller one of the list (never a larger one: it
    would not fit); Q4_K_M preferred. None when none of the list is there."""
    names = [repo for repo, _label, _need in hardware.LOCAL_MODELS]
    start = names.index(recommended) if recommended in names else 0
    pairs = [_named(i) for i in items]
    for repo in names[start:]:
        mine = [(n, p) for n, p in pairs if _short(repo) in n.lower().replace(':', '-')]
        if mine:
            return sorted(mine, key=lambda np: ('q4_k_m' not in np[0].lower(), np[0]))[0][1]
    return None


def _version(path):
    numbers = re.findall(r'\d+', path.parent.name)
    return tuple(int(n) for n in numbers[-3:]) if numbers else (0,)


def runtime_kind(path):
    text = Path(path).parent.name.lower()
    for kind in ('cuda', 'vulkan', 'metal', 'rocm', 'cpu'):
        if kind in text:
            return kind
    return 'unknown'


def pick_runtime(paths, gpu_gib=None, mac=False):
    """The newest llama-server of the best kind for this computer: CUDA on an NVIDIA card,
    then Vulkan (any card), Metal on a Mac; a CPU build only when nothing else is there."""
    if mac:
        order = ['metal', 'unknown', 'cpu']
    elif gpu_gib:
        order = ['cuda', 'vulkan', 'unknown', 'cpu']
    else:
        order = ['vulkan', 'unknown', 'cpu']
    usable = [p for p in paths if runtime_kind(p) in order]
    if not usable:
        return None
    return sorted(usable, key=lambda p: (order.index(runtime_kind(p)), tuple(-v for v in _version(p))))[0]


def apply(config, model, executable):
    """Use this model and llama-server for the chat (as the Model library does)."""
    config.runtime['model'] = str(model)
    config.runtime['executable'] = str(executable)
    config.runtime['gpu_layers'] = 0 if runtime_kind(executable) == 'cpu' else 99
    config.provider = 'local'
    config.base_url = 'http://127.0.0.1:1234/v1'
    config.api_key_env = ''
    config.thinking_backend = 'llama_cpp'
    # the 27B model is run with the 64k context it was tested with
    if '27b' in Path(model).name.lower() and config.context_tokens < 65536:
        config.context_tokens = 65536


def recommendation():
    """(recommended repo, why, graphics memory or None, Apple Silicon)."""
    mac = hardware.apple_silicon()
    gpu = None if mac else hardware.gpu_memory_gib()
    repo, why = (hardware.recommended_model(ram_gib=hardware.system_memory_gib(), unified=True)
                 if mac else hardware.recommended_model(gpu_gib=gpu))
    return repo, why, gpu, mac


def setup(config, emit=lambda progress: None, cancel=None, download=True, model=None):
    """Use `model` (else the best one found on this computer, else download the recommended
    one when `download`) with a llama-server found here (else the official one, downloaded).
    Returns a sentence saying what was chosen; LookupError when something is missing and
    `download` is False."""
    import threading
    from . import downloads
    cancel = cancel or threading.Event()
    storage = config.storage()
    recommended, why, gpu, mac = recommendation()
    notes = []
    if model is None:
        model = pick_model(local_models(storage), recommended)
        if model is None:
            if not download:
                raise LookupError('No local model found on this computer.')
            files = downloads.model_files(recommended)
            main = [f for f in files if not f['name'].lower().startswith('mmproj')]
            item = sorted(main, key=lambda f: ('q4_k_m' not in f['name'].lower(), f['size']))[0]
            model = downloads.download_model(item, storage, emit, cancel)
            projectors = sorted((f for f in files if f['name'].lower().startswith('mmproj')), key=lambda f: f['size'])
            if projectors:           # lets the model see the figure previews
                downloads.download_model(projectors[0], storage, emit, cancel)
            notes.append(f'downloaded {Path(model).name}')
        else:
            notes.append(f'{Path(model).name} found in {where(model)}')
    else:
        notes.append(f'{Path(model).name} from {where(model)}')
    executable = pick_runtime(find_runtimes(runtime_folders(storage)), gpu, mac)
    if executable is None:
        if not download:
            raise LookupError('No llama-server found on this computer.')
        backend = 'metal' if platform.system() == 'Darwin' else ('vulkan' if gpu or platform.system() == 'Windows' else 'cpu')
        executable = downloads.install_runtime(downloads.check_runtime(backend), storage, emit, cancel)
        notes.append(f'installed llama.cpp ({backend})')
    else:
        notes.append(f'llama.cpp ({runtime_kind(executable)}) found in {where(executable)}')
    apply(config, model, executable)
    return 'Local model set up: ' + '; '.join(notes) + '.' + (f' Recommended for this computer: {why}.' if why else '')
