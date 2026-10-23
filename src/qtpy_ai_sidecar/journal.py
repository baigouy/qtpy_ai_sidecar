"""Append-only diagnostics; configs and model credentials are never exported."""
from datetime import datetime, timezone
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

    def export(self, destination):
        events = [json.loads(line) for line in self.path.read_text(encoding='utf-8').splitlines()] if self.path.exists() else []
        text = '\n\n'.join(f"### {e['kind']} ({e['time']})\n\n" + (e['value'] if isinstance(e['value'], str) else
                            '```json\n' + json.dumps(e['value'], indent=2, ensure_ascii=False) + '\n```') for e in events)
        with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as out:
            out.writestr('conversation.md', text)
            out.writestr('events.jsonl', '\n'.join(json.dumps(e, ensure_ascii=False) for e in events))
            out.writestr('README.txt', 'Local debugging export. May contain document content, paths and conversation text. Review before sharing. No configuration or document files included.\n')
