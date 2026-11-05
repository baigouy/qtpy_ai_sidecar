"""Append-only diagnostics; configs and model credentials are never exported."""
from datetime import datetime, timezone
import base64
import binascii
from pathlib import Path
import json
import re
import uuid
import zipfile


def redact(value):
    if isinstance(value, dict):
        return {k: ('[REDACTED]' if re.search(r'(token|password|secret|api.?key|authorization)', k, re.I)
                    and k not in ('prompt_tokens', 'completion_tokens', 'total_tokens', 'context_tokens', 'output_tokens')
                    else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return re.sub(r'(?i)(bearer\s+)[\w.\-]+', r'\1[REDACTED]', value)
    return value


class Journal:
    def __init__(self, root):
        self.path = Path(root) / 'chats' / (datetime.now().strftime('%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:8] + '.jsonl')
        self.secrets = set()

    def add_secret(self, value):
        if value:
            self.secrets.add(value)

    def record(self, kind, value):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        event = {'time': datetime.now(timezone.utc).isoformat(), 'kind': kind, 'value': redact(value)}
        with self.path.open('a', encoding='utf-8') as out:
            serialized = json.dumps(event, ensure_ascii=False)
            for secret in self.secrets:
                serialized = serialized.replace(secret, '[REDACTED]')
            out.write(serialized + '\n')

    @property
    def images(self):
        """Folder next to the log holding the pictures shown in the chat."""
        return self.path.parent / (self.path.stem + '_images')

    def record_image(self, data, mime='image/png', source=None):
        """Keep a picture the chat displayed (a canvas snapshot) for the export.

        A log entry without the picture is useless for debugging a visual edit.
        """
        ext = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp',
               'image/gif': '.gif'}.get(str(mime or '').lower(), '.png')
        try:
            raw = base64.b64decode(data, validate=True)
        except (binascii.Error, TypeError, ValueError) as exc:
            self.record('image', {'error': 'undecodable image: ' + str(exc), 'mime': mime, 'source': source})
            return None
        self.images.mkdir(parents=True, exist_ok=True)
        name = f'{len(list(self.images.iterdir())) + 1:03d}{ext}'
        (self.images / name).write_bytes(raw)
        self.record('image', {'file': name, 'mime': mime, 'source': source})
        return self.images / name

    def export(self, destination, screenshots=None):
        """Zip the log, the pictures shown in the chat, the before/after previews
        and `screenshots` ({name: PNG bytes}, e.g. the window at export time)."""
        events = [json.loads(line) for line in self.path.read_text(encoding='utf-8').splitlines()] if self.path.exists() else []
        pictures = {}                    # name in the zip -> file on disk

        def section(e):
            value = e['value']
            head = f"### {e['kind']} ({e['time']})\n\n"
            if e['kind'] == 'image' and isinstance(value, dict) and value.get('file'):
                src = self.images / value['file']
                if src.is_file():
                    pictures['images/' + value['file']] = src
                    return head + f"![{value.get('source') or 'image'}](images/{value['file']})"
            body = value if isinstance(value, str) else '```json\n' + json.dumps(value, indent=2, ensure_ascii=False) + '\n```'
            if isinstance(value, dict) and value.get('before') and value.get('after'):
                links = []
                for side in ('before', 'after'):
                    src = Path(value[side]).with_suffix('.png')
                    if src.is_file():
                        name = f"images/preview_{len(pictures) + 1:03d}_{side}.png"
                        pictures[name] = src
                        links.append(f"![{side}]({name})")
                body += ('\n\n' + ' '.join(links)) if links else ''
            return head + body

        text = '\n\n'.join(section(e) for e in events)
        shots = dict(screenshots or {})
        if shots:
            text += '\n\n## Screenshots at export\n\n' + '\n\n'.join(f"![{n}](screenshots/{n})" for n in shots)
        with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as out:
            out.writestr('conversation.md', text)
            out.writestr('events.jsonl', '\n'.join(json.dumps(e, ensure_ascii=False) for e in events))
            for name, src in pictures.items():
                out.write(src, name)
            for name, data in shots.items():
                out.writestr('screenshots/' + name, data)
            out.writestr('README.txt', 'Local debugging export. May contain document content, paths, conversation text, '
                         'the pictures shown in the chat (images/) and a screenshot of the application window (screenshots/). '
                         'Review before sharing. No configuration or document files included.\n')
