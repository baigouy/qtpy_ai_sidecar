"""Explicit managed downloads, pinned revisions and SHA256 verification."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import stat
import tarfile
import tempfile
import time
from urllib.parse import quote
import zipfile
import httpx


def metadata(url, headers=None):
    with httpx.Client(follow_redirects=True, timeout=30) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        return response.json()


def hf_headers():
    value = os.environ.get('HF_TOKEN')
    return {'Authorization': 'Bearer ' + value} if value else {}


def search_models(query):
    return [m['id'] for m in metadata('https://huggingface.co/api/models?search=' + quote(query) + '&filter=gguf&limit=15')]


def model_files(repository):
    if len(repository.split('/')) != 2 or any(p in ('', '.', '..') for p in repository.split('/')):
        raise ValueError('Use a Hugging Face repository in owner/model form')
    info = metadata('https://huggingface.co/api/models/' + quote(repository, safe='/') + '?blobs=true', hf_headers())
    return [{'repository': repository, 'revision': info['sha'], 'name': f['rfilename'],
             'size': f.get('size', f.get('lfs', {}).get('size', 0)), 'sha256': f.get('lfs', {}).get('sha256')}
            for f in info.get('siblings', []) if f['rfilename'].lower().endswith('.gguf')]


def download(url, destination, expected, emit, cancel, headers=None):
    if not expected or len(expected.removeprefix('sha256:')) != 64:
        raise ValueError('No SHA256 checksum provided; refusing unverified managed download')
    expected = expected.removeprefix('sha256:')
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + '.partial')
    digest, done, last = hashlib.sha256(), 0, 0
    try:
        with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60, connect=15)) as client:
            with client.stream('GET', url, headers=headers) as response:
                response.raise_for_status()
                total = int(response.headers.get('Content-Length', 0))
                with partial.open('wb') as out:
                    for chunk in response.iter_bytes(1024 * 1024):
                        if cancel.is_set():
                            raise InterruptedError('Download cancelled')
                        out.write(chunk)
                        digest.update(chunk)
                        done += len(chunk)
                        if time.monotonic() - last > .2:
                            emit({'downloaded': done, 'total': total})
                            last = time.monotonic()
        if cancel.is_set():
            raise InterruptedError('Download cancelled')
        if digest.hexdigest() != expected:
            raise ValueError('SHA256 mismatch; downloaded file was not installed')
        partial.replace(destination)
        emit({'downloaded': done, 'total': done})
        return destination
    finally:
        partial.unlink(missing_ok=True)


def download_model(item, root, emit, cancel):
    filename = PurePosixPath(item['name'])
    if filename.is_absolute() or '..' in filename.parts or '\\' in item['name']:
        raise ValueError('Unsafe model filename')
    # Split GGUFs must be installed as a complete set; do not present a broken load.
    import re
    if re.search(r'-\d{5}-of-\d{5}\.gguf$', str(filename), re.I):
        raise ValueError('Split GGUF sets are not supported by this first downloader. Select a single-file quantization.')
    revision = item['revision']
    if not re.fullmatch(r'[0-9a-fA-F]{40,64}', revision):
        raise ValueError('Expected a pinned model revision')
    repo_folder = hashlib.sha256(item['repository'].encode()).hexdigest()[:12]
    path = Path(root) / 'models' / repo_folder / revision / str(filename)
    url = 'https://huggingface.co/' + quote(item['repository'], safe='/') + '/resolve/' + revision + '/' + quote(item['name'], safe='/')
    result = download(url, path, item['sha256'], emit, cancel, hf_headers())
    result.with_suffix('.provenance.json').write_text(json.dumps(item, indent=2), encoding='utf-8')
    return result


def asset_suffix(system, machine, backend):
    architecture = {'amd64': 'x64', 'x86_64': 'x64', 'arm64': 'arm64', 'aarch64': 'arm64'}.get(machine.lower())
    if not architecture:
        raise ValueError('No managed runtime mapping for this architecture; use an existing executable')
    if system == 'Windows' and backend in ('vulkan', 'cpu'):
        return '-bin-win-' + backend + '-' + architecture + '.zip'
    if system == 'Darwin' and backend in ('metal', 'cpu'):
        return '-bin-macos-' + architecture + '.tar.gz'
    if system == 'Linux' and backend in ('vulkan', 'cpu'):
        return '-bin-ubuntu-' + ('vulkan-' if backend == 'vulkan' else '') + architecture + '.tar.gz'
    raise ValueError('No official runtime mapping for this OS/backend; use an existing executable')


def check_runtime(backend='vulkan'):
    system, machine = platform.system(), platform.machine()
    suffix = asset_suffix(system, machine, backend)
    releases = metadata('https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=15')
    for release in releases:
        if release.get('draft') or release.get('prerelease'):
            continue
        for asset in release.get('assets', []):
            if asset['name'].endswith(suffix):
                return {'tag': release['tag_name'], 'backend': backend, 'name': asset['name'],
                        'url': asset['browser_download_url'], 'sha256': asset.get('digest'), 'size': asset['size'],
                        'system': system, 'architecture': machine}
    raise ValueError('No compatible official runtime found in recent releases')


def extract_runtime(archive, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    root = folder.resolve()
    if str(archive).endswith('.zip'):
      with zipfile.ZipFile(archive) as zipped:
        if sum(entry.file_size for entry in zipped.infolist()) > 4 * 1024**3:
            raise ValueError('Runtime archive is unexpectedly large')
        for entry in zipped.infolist():
            target = (root / entry.filename).resolve()
            mode = entry.external_attr >> 16
            if not target.is_relative_to(root) or stat.S_ISLNK(mode):
                raise ValueError('Unsafe runtime archive member')
        zipped.extractall(root)
    else:
        with tarfile.open(archive, 'r:*') as packed:
            members = packed.getmembers()
            if sum(m.size for m in members) > 4 * 1024**3:
                raise ValueError('Runtime archive is unexpectedly large')
            links = []
            for member in members:
                target = (root / member.name).resolve()
                if not target.is_relative_to(root):
                    raise ValueError('Unsafe runtime archive member')
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with packed.extractfile(member) as source, target.open('wb') as out:
                        shutil.copyfileobj(source, out)
                    target.chmod(member.mode & 0o777)
                elif member.issym() or member.islnk():
                    destination = ((target.parent if member.issym() else root) / member.linkname).resolve()
                    if not destination.is_relative_to(root):
                        raise ValueError('Unsafe runtime archive link')
                    links.append((target, destination, member.issym()))
                else:
                    raise ValueError('Unsupported special archive member')
            for target, destination, symbolic in links:
                if not destination.resolve().is_relative_to(root):
                    raise ValueError('Unsafe runtime archive link chain')
                target.parent.mkdir(parents=True, exist_ok=True)
                if symbolic:
                    target.symlink_to(os.path.relpath(destination, target.parent))
                else:
                    os.link(destination, target)
    binaries = list(root.rglob('llama-server.exe')) + list(root.rglob('llama-server'))
    if len(binaries) != 1:
        raise ValueError('Expected exactly one llama-server executable')
    return binaries[0]


def install_runtime(item, root, emit, cancel):
    root = Path(root)
    import re
    if not re.fullmatch(r'[\w.\-]+', item['tag']) or item['backend'] not in ('vulkan', 'cpu', 'metal'):
        raise ValueError('Invalid runtime release identity')
    folder = root / 'runtimes' / (item['tag'] + '-' + item['backend'] + '-' + platform.system() + '-' + platform.machine())
    if folder.exists():
        binaries = list(folder.rglob('llama-server.exe')) + list(folder.rglob('llama-server'))
        if len(binaries) == 1:
            return binaries[0]
        raise ValueError('Existing runtime folder is incomplete; choose another release')
    archive = download(item['url'], root / 'downloads' / item['name'], item['sha256'], emit, cancel)
    folder.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='install-', dir=folder.parent))
    try:
        executable = extract_runtime(archive, staging)
        relative = executable.relative_to(staging)
        (staging / 'release.json').write_text(json.dumps(item, indent=2), encoding='utf-8')
        if cancel.is_set():
            raise InterruptedError('Runtime installation cancelled')
        staging.rename(folder)
        return folder / relative
    finally:
        if staging.exists():
            shutil.rmtree(staging)
