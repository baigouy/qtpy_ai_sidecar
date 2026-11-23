"""Optional owned llama.cpp process. Never installs globally or stops other servers."""
import asyncio
import re
import secrets
import socket
import subprocess
from pathlib import Path
import httpx


def reasoning_control(template):
    """How a chat template lets reasoning be steered: 'toggle' (enable_thinking), 'strength'
    (only a 'Reasoning strength: <level>' system line, e.g. Muse-Glimmer; reasoning cannot be
    switched off) or None (unknown)."""
    if 'enable_thinking' in template:
        return 'toggle'
    if re.search(r'reasoning[ _]strength', template, re.I):
        return 'strength'
    return None


def vision_projector(settings):
    """The multimodal projector the owned llama-server loads so the model sees
    images: settings['mmproj'] when it names a file, none when it is '' / False /
    'off', else ('auto', the default) an mmproj*.gguf next to the model, as LM
    Studio and Hugging Face ship them. Without it every local model was text-only
    and asked the user for coordinates it could have read from the preview."""
    choice = settings.get('mmproj', 'auto')
    if choice in ('', False, None, 'off', 'none'):
        return None
    if choice != 'auto':
        path = Path(choice)
        return path if path.is_file() else None
    model = Path(settings.get('model') or '')
    if not model.name:
        return None
    try:
        found = sorted(model.parent.glob('mmproj*.gguf'))
    except OSError:
        return None
    return found[0] if found else None


class OwnedLlama:
    def __init__(self, config):
        self.config = config
        self.process = None
        self.log = None
        self.url = None
        self.key = secrets.token_urlsafe(32)
        self.reasoning_control = None   # 'toggle', 'strength' or None, read from the loaded chat template

    async def _read_template(self, client):
        try:
            response = await client.get(self.url + '/props', headers={'Authorization': 'Bearer ' + self.key})
            self.reasoning_control = reasoning_control(response.json().get('chat_template') or '')
        except (httpx.HTTPError, ValueError, AttributeError):
            self.reasoning_control = None

    @property
    def raw_qwen(self):
        protocol = self.config.runtime.get('protocol', 'auto')
        named = str(self.config.runtime.get('model_name') or '') + ' ' + str(self.config.runtime.get('model', ''))
        return protocol == 'qwen_xml' or (protocol == 'auto' and 'qwen3.5' in named.lower())

    async def ensure(self, cancel, emit):
        if self.process and self.process.poll() is None:
            return self.url, self.key
        self.stop()
        settings = self.config.runtime
        executable, model = Path(settings['executable']), Path(settings['model'])
        from .discover import is_gguf          # an Ollama model is a GGUF without the extension
        if not executable.is_file() or not model.is_file() or not (model.suffix.lower() == '.gguf' or is_gguf(model)):
            raise ValueError('The local model or llama.cpp is missing (moved or deleted?). '
                             'Set it up again with the Model button.')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        self.url = f'http://127.0.0.1:{port}'
        folder = self.config.storage()
        folder.mkdir(parents=True, exist_ok=True)
        log_path = folder / 'llama-server.log'
        self.log = log_path.open('w', encoding='utf-8')
        command = [str(executable), '-m', str(model), '--host', '127.0.0.1', '--port', str(port),
                   '--api-key', self.key, '--jinja', '-c', str(self.config.context_tokens),
                   '-np', '1', '-ngl', str(0 if settings.get('force_cpu') else settings.get('gpu_layers', 99))]
        if settings.get('force_cpu'):
            command += ['--device', 'none', '--no-op-offload', '--no-kv-offload']
        projector = vision_projector(settings)
        if projector is not None:            # the model can see the previews tools return
            command += ['--mmproj', str(projector)]
            if settings.get('force_cpu'):
                command += ['--no-mmproj-offload']
        template = settings.get('chat_template')
        if self.raw_qwen:
            command += ['--skip-chat-parsing', '--reasoning-format', 'none']
            template = template or Path(__file__).parent / 'resources' / 'qwen_tools.jinja'
        if template:
            command += ['--chat-template-file', str(template)]
        if settings.get('threads', 0) > 0:
            command += ['--threads', str(settings['threads'])]
        if self.config.thinking_budget >= 0:
            command += ['--reasoning-budget', str(self.config.thinking_budget)]
        from .discover import runtime_environment     # LM Studio's builds need their vendor libraries
        self.process = subprocess.Popen(command, cwd=executable.parent, stdout=self.log, env=runtime_environment(executable),
            stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            async with httpx.AsyncClient(timeout=1) as client:
                for _ in range(600):
                    if cancel.is_set():
                        raise InterruptedError('Model loading stopped')
                    if self.process.poll() is not None:
                        raise RuntimeError(self.exit_reason(log_path))
                    try:
                        response = await client.get(self.url + '/health', headers={'Authorization': 'Bearer ' + self.key})
                        if response.status_code == 200:
                            await self._read_template(client)
                            emit('status', 'Local model ready')
                            return self.url, self.key
                    except httpx.HTTPError:
                        pass
                    emit('status', 'Loading local model…')
                    await asyncio.sleep(.5)
            raise TimeoutError('Model loading exceeded five minutes')
        except BaseException:
            self.stop()
            raise

    def exit_reason(self, log_path):
        """Why llama.cpp stopped while loading, in plain words (user 2026-11-23: "Owned llama.cpp
        exited" with an empty log told nothing)."""
        try:
            self.log.flush()
            lines = [l for l in Path(log_path).read_text(encoding='utf-8', errors='replace').splitlines() if l.strip()]
        except OSError:
            lines = []
        tail = ' '.join(lines[-3:])[-400:]
        low = tail.lower()
        if not lines:
            why = 'llama.cpp could not start (a missing library?).'
        elif 'out of memory' in low or 'failed to allocate' in low or 'cudamalloc' in low:
            why = ('The model does not fit in the graphics memory. Close other programs using it (LM Studio, '
                   'games), or choose a smaller model.')
        elif 'unknown model architecture' in low or 'failed to load model' in low:
            why = 'This llama.cpp cannot read this model (too old for it, or not a supported model).'
        else:
            why = 'llama.cpp stopped while loading the model.'
        return (why + (f' Last message: {tail}' if tail else '') + f' Full log: {log_path}. '
                'Choose another model or set it up again with the Model button, or use an online service.')

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self.process = None
        if self.log:
            self.log.close()
            self.log = None
