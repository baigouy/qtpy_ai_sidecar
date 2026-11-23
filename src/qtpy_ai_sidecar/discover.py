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
                    if blob.is_file() and is_gguf(blob):     # (Ollama's newer engine has other formats)
                        found.append((path.parent.name + ':' + tag, blob))
    return found


def is_gguf(path):
    """A GGUF file, by its first bytes (Ollama's blobs have no .gguf extension)."""
    try:
        with open(path, 'rb') as f:
            return f.read(4) == b'GGUF'
    except OSError:
        return False


def works(executable):
    """(True, '') when this llama-server starts (--version, with its libraries); else (False, why)."""
    import subprocess
    try:
        r = subprocess.run([str(executable), '--version'], cwd=str(Path(executable).parent),
                           env=runtime_environment(executable), capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=60,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if r.returncode == 0:
        return True, ''
    text = (r.stdout + r.stderr).strip().splitlines()
    return False, (text[-1] if text else f'exit code {r.returncode}, no message (a missing library?)')


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


def library_folders(executable):
    """Folders a llama-server needs on its library path: an LM Studio backend's
    backend-manifest.json names vendor packages (CUDA, Vulkan libraries) kept in
    backends/vendor/<name>; without them it exits at once with nothing in its log."""
    folder = Path(executable).parent
    try:
        manifest = json.loads((folder / 'backend-manifest.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return [], []
    names = manifest.get('vendor_lib_package_names') or []
    wanted = [folder.parent / 'vendor' / n for n in names]
    return [w for w in wanted if w.is_dir()], [w for w in wanted if not w.is_dir()]


def runtime_environment(executable, base=None):
    """The environment to start this llama-server with (its vendor libraries on the path)."""
    env = dict(os.environ if base is None else base)
    found, _missing = library_folders(executable)
    if found:
        system = platform.system()
        var = 'PATH' if system == 'Windows' else ('DYLD_LIBRARY_PATH' if system == 'Darwin' else 'LD_LIBRARY_PATH')
        env[var] = os.pathsep.join([str(f) for f in found] + ([env[var]] if env.get(var) else []))
    return env


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


def ranked_runtimes(paths, gpu_gib=None, mac=False):
    """llama-server builds, best first: CUDA on an NVIDIA card, then Vulkan (any card), Metal
    on a Mac, a CPU build last; the newest first within each kind."""
    if mac:
        order = ['metal', 'unknown', 'cpu']
    elif gpu_gib:
        order = ['cuda', 'vulkan', 'unknown', 'cpu']
    else:
        order = ['vulkan', 'unknown', 'cpu']
    usable = [p for p in paths if runtime_kind(p) in order and not library_folders(p)[1]]
    return sorted(usable, key=lambda p: (order.index(runtime_kind(p)), tuple(-v for v in _version(p))))


def pick_runtime(paths, gpu_gib=None, mac=False):
    ranked = ranked_runtimes(paths, gpu_gib, mac)
    return ranked[0] if ranked else None


def apply(config, model, executable, name=None):
    """Use this model and llama-server for the chat (as the Model library does). `name`: the
    model's name when its file does not say it (an Ollama blob)."""
    config.runtime['model'] = str(model)
    config.runtime['model_name'] = name or Path(model).stem
    config.runtime['executable'] = str(executable)
    config.runtime['gpu_layers'] = 0 if runtime_kind(executable) == 'cpu' else 99
    config.provider = 'local'
    config.base_url = 'http://127.0.0.1:1234/v1'
    config.api_key_env = ''
    config.thinking_backend = 'llama_cpp'
    # the 27B model is run with the 64k context it was tested with
    if '27b' in config.runtime['model_name'].lower() and config.context_tokens < 65536:
        config.context_tokens = 65536


def recommendation():
    """(recommended repo, why, graphics memory or None, Apple Silicon)."""
    mac = hardware.apple_silicon()
    gpu = None if mac else hardware.gpu_memory_gib()
    repo, why = (hardware.recommended_model(ram_gib=hardware.system_memory_gib(), unified=True)
                 if mac else hardware.recommended_model(gpu_gib=gpu))
    return repo, why, gpu, mac


def official_backend(gpu, mac):
    if mac or platform.system() == 'Darwin':
        return 'metal'
    return 'vulkan' if gpu or platform.system() == 'Windows' else 'cpu'


def plan(config, model=None, name=None, say=lambda text: None):
    """What the local set-up will use, without downloading anything: a dict with 'model',
    'name', 'executable' (None when missing), 'download_model' (the repository to fetch, or
    None), 'download_runtime' (the official llama.cpp build to fetch, or None), 'notes', 'why'
    and 'problems' (llama-server builds found here that do not start, and why)."""
    storage = config.storage()
    recommended, why, gpu, mac = recommendation()
    out = {'model': None, 'name': name, 'executable': None, 'download_model': None,
           'download_runtime': None, 'notes': [], 'why': why, 'problems': []}
    if model is not None:
        out['model'] = Path(model)
        out['notes'].append(f'{name or Path(model).stem} from {where(model)}')
    else:
        say('Looking for models on this computer…')
        models = local_models(storage)
        best = pick_model(models, recommended)
        if best is None:
            out['download_model'] = recommended
        else:
            out['model'] = best
            out['name'] = next((m['name'] for m in models if m['path'] == best), best.stem)
            out['notes'].append(f"{out['name']} found in {where(best)}")
    say('Checking llama.cpp on this computer…')
    for executable in ranked_runtimes(find_runtimes(runtime_folders(storage)), gpu, mac):
        ok, problem = works(executable)
        if ok:
            out['executable'] = executable
            out['notes'].append(f'llama.cpp ({runtime_kind(executable)}) found in {where(executable)}')
            break
        out['problems'].append(f'{executable}: {problem}')
    if out['executable'] is None:
        out['download_runtime'] = official_backend(gpu, mac)
    return out


def download_text(p):
    """What a plan will download, for the user to agree to first; '' when nothing."""
    lines = []
    if p['download_model']:
        repo = p['download_model']
        size = hardware.DOWNLOAD_GB.get(repo)
        lines.append(f"• the model {repo.split('/')[-1].replace('-GGUF', '')}"
                     + (f' (about {size} GB)' if size else '') + ' from Hugging Face (huggingface.co)')
    if p['download_runtime']:
        lines.append(f"• llama.cpp, which runs the model (official {p['download_runtime']} build, "
                     'about 50 to 200 MB) from GitHub (github.com/ggml-org/llama.cpp)')
    return '\n'.join(lines)


def run_plan(config, p, emit=lambda progress: None, cancel=None, say=lambda text: None):
    """Download what the plan lacks (the user has agreed), check llama.cpp starts, use it all.
    Returns a sentence saying what was chosen; raises with a plain message on failure."""
    import threading
    from . import downloads
    cancel = cancel or threading.Event()
    storage = config.storage()
    model, name, executable, notes = p['model'], p['name'], p['executable'], list(p['notes'])
    if p['download_model']:
        say('Asking Hugging Face for the model files…')
        try:
            files = downloads.model_files(p['download_model'])
        except Exception as exc:
            raise RuntimeError(f'Could not reach Hugging Face to download the model ({exc}). '
                               'Check the internet connection, or use a model already on this computer.') from exc
        main = [f for f in files if not f['name'].lower().startswith('mmproj')]
        item = sorted(main, key=lambda f: ('q4_k_m' not in f['name'].lower(), f['size']))[0]
        projectors = sorted((f for f in files if f['name'].lower().startswith('mmproj')), key=lambda f: f['size'])
        say(f"Downloading the model {item['name']} ({item['size'] / 1024**3:.1f} GB)…")
        model = downloads.download_model(item, storage, emit, cancel)
        if projectors:           # lets the model see the figure previews
            say(f"Downloading its image reader {projectors[0]['name']} ({projectors[0]['size'] / 1024**3:.1f} GB)…")
            downloads.download_model(projectors[0], storage, emit, cancel)
        name = Path(model).stem
        notes.insert(0, f'downloaded {Path(model).name}')
    if p['download_runtime']:
        say('Asking GitHub for the official llama.cpp build…')
        try:
            release = downloads.check_runtime(p['download_runtime'])
        except Exception as exc:
            raise RuntimeError(f'Could not reach GitHub to download llama.cpp ({exc}). '
                               'Check the internet connection.') from exc
        say(f"Downloading llama.cpp {release.get('tag', '')} ({p['download_runtime']})…")
        executable = downloads.install_runtime(release, storage, emit, cancel)
        ok, problem = works(executable)
        if not ok:
            raise RuntimeError(f'The downloaded llama.cpp does not start on this computer: {problem}')
        notes.append(f"installed llama.cpp ({p['download_runtime']})")
    if model is None or executable is None:
        raise RuntimeError('Nothing to run: no model or no llama.cpp.')
    apply(config, model, executable, name)
    why = p.get('why')
    return 'Local model set up: ' + '; '.join(notes) + '.' + (f' Recommended for this computer: {why}.' if why else '')


def setup(config, emit=lambda progress: None, cancel=None, download=True, model=None, name=None):
    """plan + run_plan in one call. With download False, LookupError when something would
    have to be downloaded (nothing is fetched without the user's yes)."""
    p = plan(config, model, name)
    if not download and (p['download_model'] or p['download_runtime']):
        raise LookupError('Not found on this computer:\n' + download_text(p))
    return run_plan(config, p, emit, cancel)
