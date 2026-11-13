"""Chats as procedures: the MCP calls a chat made, saved and run again without the model.

For any application connected to the sidecar:
- a chat's journal (or the "sidecar-debug" zip of its Debug export) is read as steps,
  each one MCP call with the request it answered and what it returned;
- the steps that changed the application (not the reads, the failed calls, a reply
  undone with its Undo button, an edit the chat undid itself) are saved as a procedure
  file (JSON) and run again, all at once or one by one, through the same MCP servers.

The application adapter may say which calls only read, undo, redo or are to be skipped
(``procedure_role(name, arguments)``) and how a call reads to a person
(``describe_call``); without it, names starting with get_/list_/inspect_/... read.

Procedure file::

    {"procedure": 1, "application": "PyFigures",
     "steps": [{"request": "rotate all by 25", "call": "use_pyfigures_tool",
                "arguments": {...}}, ...]}

Paths under the folder of the document the chat worked on (state "document" with
"folder" and "name", when the application gives it) are saved as {folder} / {name},
filled with the document a procedure runs on.
"""
from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

FORMAT = 1
_READ_PREFIXES = ('get_', 'list_', 'inspect_', 'describe_', 'check_', 'preview_', 'explain_', 'find_',
                  'search_', 'read_', 'show_')


@dataclass
class Step:
    """One MCP call of a chat."""
    request: str
    turn: int
    call: str
    arguments: dict = field(default_factory=dict)
    role: str = 'edit'                  # edit, read, undo, redo, skip
    recorded_error: bool = False
    recorded_result: str = ''
    turn_undone: bool = False


def default_role(name, arguments) -> str:
    if name.startswith(_READ_PREFIXES) or (arguments or {}).get('dry_run'):
        return 'read'
    if name in ('undo', 'redo'):
        return name
    return 'edit'


def role_of(adapter, name, arguments) -> str:
    hook = getattr(adapter, 'procedure_role', None) if adapter is not None else None
    role = hook(name, arguments) if hook else None
    if role:
        return role
    reads = getattr(adapter, 'is_read_only_call', None) if adapter is not None else None
    if reads and reads(name, arguments) is True:
        return 'read'
    return default_role(name, arguments)


def describe(adapter, step) -> str:
    hook = getattr(adapter, 'describe_call', None) if adapter is not None else None
    if hook:
        try:
            return hook(step.call, step.arguments)
        except Exception:
            pass
    return step.call + ' ' + json.dumps(step.arguments, ensure_ascii=False)


def read_events(path) -> list[dict]:
    """The events of a chat journal (.jsonl) or of a sidecar-debug zip."""
    path = Path(path)
    if path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as z:
            name = next((n for n in z.namelist() if n.endswith('events.jsonl')), None)
            if name is None:
                raise ValueError(f'{path.name} has no events.jsonl (not a chat debug export)')
            lines = z.read(name).decode('utf-8').splitlines()
    else:
        lines = path.read_text(encoding='utf-8').splitlines()
    events = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    return events


def load_steps(path, adapter=None, events=None) -> list[Step]:
    """Every MCP call of the chat *path*, in order, with the request it answered."""
    steps, pending, undone, turns = [], [], set(), {}
    request, turn = '', 0
    for event in (events if events is not None else read_events(path)):
        kind, value = event.get('kind'), event.get('value')
        if kind == 'user':
            request, turn = str(value), turn + 1
            turns.setdefault(request, []).append(turn)
        elif kind == 'action' and isinstance(value, dict) and value.get('status') == 'undone':
            undone.update(turns.get(str(value.get('request')), []))
        elif kind == 'tool_call' and isinstance(value, dict) and value.get('name'):
            args = value.get('arguments') or {}
            step = Step(request, turn, value['name'], dict(args) if isinstance(args, dict) else {})
            step.role = role_of(adapter, step.call, step.arguments)
            steps.append(step)
            pending.append(step)
        elif kind == 'tool_result' and pending:
            step = pending.pop(0)
            if isinstance(value, dict):
                step.recorded_error = bool(value.get('is_error'))
                step.recorded_result = str(value.get('content', ''))[:4000]
    for step in steps:
        step.turn_undone = step.turn in undone
    return steps


@dataclass
class Turn:
    """One request of a chat and what followed it, in order: ('assistant', text),
    ('call', Step) and ('error', text) items."""
    request: str
    items: list = field(default_factory=list)
    undone: bool = False
    seconds: float = 0.0                # from the request to the last event of the turn
    # a setup turn (user event with "setup": true) puts the document in a known state:
    # its recorded calls always run, also in a live replay, and the model is not asked
    setup: bool = False

    def calls(self):
        return [s for kind, s in self.items if kind == 'call']

    def answers(self):
        return [t for kind, t in self.items if kind == 'assistant']


def _when(event):
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(event.get('time')))
    except (TypeError, ValueError):
        return None


def compare(adapter, then_steps, now_steps) -> dict:
    """How the edits a model made for one request compare between two runs."""
    then = [describe(adapter, s) for s in kept_steps(then_steps)]
    now = [describe(adapter, s) for s in kept_steps(now_steps)]
    op = lambda text: text.split(' ', 1)[0]
    if then == now:
        verdict = 'same edits'
    elif [op(t) for t in then] == [op(t) for t in now]:
        verdict = 'same operations, other arguments'
    elif not now and then:
        verdict = 'no edit now'
    else:
        verdict = 'different edits'
    return {'verdict': verdict, 'then': then, 'now': now,
            'calls_then': len(then_steps), 'calls_now': len(now_steps),
            'failed_now': sum(1 for s in now_steps if s.recorded_error)}


def load_turns(path, adapter=None) -> list[Turn]:
    """The conversation of a chat log / debug zip, request by request: the model's
    texts and its calls (each with its role and what it gave then)."""
    turns, events = [], read_events(path)          # read once: a chat log can be several MB
    steps = iter(load_steps(path, adapter, events))
    start = None
    for event in events:
        kind, value = event.get('kind'), event.get('value')
        if kind == 'user':
            turns.append(Turn(str(value), setup=bool(event.get('setup'))))
            start = _when(event)
            continue
        if not turns:
            continue
        when = _when(event)
        if start and when:
            turns[-1].seconds = max(turns[-1].seconds, (when - start).total_seconds())
        if kind == 'assistant' and str(value or '').strip():
            turns[-1].items.append(('assistant', str(value)))
        elif kind == 'error':
            turns[-1].items.append(('error', str(value)))
        elif kind == 'tool_call' and isinstance(value, dict) and value.get('name'):
            step = next(steps, None)
            if step is not None:
                turns[-1].items.append(('call', step))
    for turn in turns:
        turn.undone = any(s.turn_undone for kind, s in turn.items if kind == 'call')
    return turns


def kept_steps(steps) -> list[Step]:
    """The edits that stayed: not the reads or skipped calls, not the failed calls, not a
    reply undone with its Undo button, not an edit the chat undid (a redo puts it back)."""
    kept, undone = [], []
    for s in steps:
        if s.role in ('undo', 'redo'):
            if s.recorded_error:
                continue
            if s.role == 'redo':
                if undone:
                    kept.append(undone.pop())
            elif kept:
                undone.append(kept.pop())       # one call = one undo step
            continue
        if s.role != 'edit' or s.recorded_error or s.turn_undone:
            continue
        kept.append(s)
        undone.clear()
    return kept


def document_of(path):
    """(folder, name) of the document the chat worked on, from its state, if given."""
    for event in read_events(path):
        if event.get('kind') == 'host_context' and isinstance(event.get('value'), dict):
            doc = event['value'].get('document') or {}
            if doc.get('folder') and doc.get('name'):
                return str(doc['folder']), str(doc['name'])
    return None, None


def templated(value, folder, name):
    """Paths under *folder* (and a file called *name*.ext there) as {folder} / {name}."""
    if isinstance(value, str) and folder and name and ('/' in value or '\\' in value):
        norm, base = value.replace('\\', '/'), folder.replace('\\', '/').rstrip('/')
        if norm.lower().startswith(base.lower() + '/'):
            rest = norm[len(base) + 1:]
            stem, dot, ext = rest.rpartition('.')
            if dot and stem == name:
                rest = '{name}.' + ext
            return '{folder}/' + rest
    if isinstance(value, dict):
        return {k: templated(v, folder, name) for k, v in value.items()}
    if isinstance(value, list):
        return [templated(v, folder, name) for v in value]
    return value


def filled(value, folder, name):
    if isinstance(value, str):
        return value.replace('{folder}', folder or '.').replace('{name}', name or 'document')
    if isinstance(value, dict):
        return {k: filled(v, folder, name) for k, v in value.items()}
    if isinstance(value, list):
        return [filled(v, folder, name) for v in value]
    return value


def save(steps, out_path, application='', source=None, name=None) -> str:
    """Write *steps* as a procedure file; paths of the chat's document become templates."""
    folder, doc = document_of(source) if source else (None, None)
    data = {'procedure': FORMAT, 'application': application, 'name': name or Path(out_path).stem,
            'source_chat': str(source) if source else None,
            'steps': [{'request': s.request, 'call': s.call,
                       'arguments': templated(s.arguments, folder, doc)} for s in steps]}
    Path(out_path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    return str(out_path)


def load(path) -> tuple[str, list[Step]]:
    """(application, steps) of a procedure file."""
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not isinstance(data.get('steps'), list):
        raise ValueError(f'{Path(path).name} is not a procedure (no "steps")')
    steps = []
    for k, s in enumerate(data['steps'], 1):
        if not isinstance(s, dict) or not s.get('call'):
            raise ValueError(f'step {k} of {Path(path).name} names no MCP call ("call")')
        steps.append(Step(s.get('request', ''), k, s['call'], dict(s.get('arguments') or {})))
    return str(data.get('application') or ''), steps


async def run_step(hub, step, document=(None, None)):
    """Run one step through *hub* (an open MCPHub). Returns the text it gave; raises
    with the application's error."""
    ident = next((i for i, (_, _, tool) in hub.tools.items() if tool.name == step.call), None)
    if ident is None:
        raise ValueError(f'no connected application has the operation {step.call}')
    texts = []
    result = await hub.execute(ident, filled(step.arguments, *document), lambda kind, value: None)
    if isinstance(result, dict):
        if result.get('is_error'):
            raise RuntimeError(str(result.get('error') or result.get('content') or 'failed'))
        texts.append(str(result.get('content', '')))
    else:
        texts.append(str(result))
    text = '\n'.join(texts)
    if text.lstrip().startswith('ERROR'):
        raise RuntimeError(text)
    return text
