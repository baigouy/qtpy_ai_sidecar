"""Optional owned llama.cpp process. Never installs globally or stops other servers."""
import asyncio
import secrets
import socket
import subprocess
from pathlib import Path
import httpx


class OwnedLlama:
    def __init__(self, config):
        self.config = config
        self.process = None
        self.log = None
        self.url = None
        self.key = secrets.token_urlsafe(32)

    async def ensure(self, cancel, emit):
        if self.process and self.process.poll() is None:
            return self.url, self.key
        self.stop()
        settings = self.config.runtime
        executable, model = Path(settings['executable']), Path(settings['model'])
        if not executable.is_file() or not model.is_file() or model.suffix.lower() != '.gguf':
            raise ValueError('Owned runtime requires an existing llama-server executable and GGUF model')
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
        if settings.get('chat_template'):
            command += ['--chat-template-file', str(settings['chat_template'])]
        if settings.get('threads', 0) > 0:
            command += ['--threads', str(settings['threads'])]
        if self.config.thinking_budget >= 0:
            command += ['--reasoning-budget', str(self.config.thinking_budget)]
        self.process = subprocess.Popen(command, cwd=executable.parent, stdout=self.log,
            stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            async with httpx.AsyncClient(timeout=1) as client:
                for _ in range(600):
                    if cancel.is_set():
                        raise InterruptedError('Model loading stopped')
                    if self.process.poll() is not None:
                        raise RuntimeError('Owned llama.cpp exited. See ' + str(log_path))
                    try:
                        response = await client.get(self.url + '/health', headers={'Authorization': 'Bearer ' + self.key})
                        if response.status_code == 200:
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
