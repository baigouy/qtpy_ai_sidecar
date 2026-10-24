"""Parse Qwen's final-channel protocol when llama-server native parsing is bypassed.

Only complete final-channel tool calls are eligible; never execute thinking text,
partial tags, fenced examples, unknown functions, or duplicate parameters.
"""
import json
import re
import uuid


def parse_reply(raw, schemas, require_think_end=False, strict=True):
    reasoning = ''
    if '</think>' in raw:
        reasoning, raw = raw.split('</think>', 1)
        reasoning = reasoning.removeprefix('<think>').strip()
    elif '<think>' in raw or (require_think_end and '<tool_call' in raw):
        raise ValueError('Incomplete thinking response; no tool submitted')
    # A plain reply without protocol tags is safe to display. In raw mode some
    # responses end naturally without a reasoning delimiter. Tool execution still
    # requires an explicit final-channel boundary when thinking was prefilled.
    blocks = list(re.finditer(r'<tool_call>(.*?)</tool_call>', raw, re.S))
    residue = re.sub(r'<tool_call>.*?</tool_call>', '', raw, flags=re.S)
    if any(tag in residue for tag in ('<tool_call', '</tool_call', '<function=', '<parameter=')):
        raise ValueError('Incomplete or malformed tool call; no tool submitted')
    calls = []
    for block in blocks:
        if raw[:block.start()].count('```') % 2:
            raise ValueError('Tool markup inside a code example is not executable')
        body = block.group(1).strip()
        match = re.fullmatch(r'<function=([A-Za-z0-9_]+)>\s*(.*?)\s*</function>', body, re.S)
        if not match:
            raise ValueError('Malformed Qwen function block; no tool submitted')
        name, fields = match.groups()
        if strict and name not in schemas:
            raise ValueError('Unknown function in model reply; no tool submitted: ' + name)
        schema = schemas.get(name, {})
        arguments = {}
        rest = re.sub(r'<parameter=([A-Za-z0-9_]+)>(.*?)</parameter>', '', fields, flags=re.S)
        if rest.strip():
            raise ValueError('Malformed parameter block; no tool submitted')
        for parameter in re.finditer(r'<parameter=([A-Za-z0-9_]+)>(.*?)</parameter>', fields, re.S):
            key, value = parameter.groups()
            if key in arguments or (strict and key not in schema.get('properties', {})):
                raise ValueError('Duplicate/unknown tool parameter; no tool submitted: ' + key)
            value = value.strip()
            try:
                decoded = json.loads(value)
            except ValueError:
                decoded = value
            if schema.get('properties', {}).get(key, {}).get('type') == 'string' and not isinstance(decoded, str):
                decoded = value
            arguments[key] = decoded
        missing = set(schema.get('required', [])) - set(arguments)
        if strict and missing:
            raise ValueError('Missing tool parameters; no tool submitted: ' + ', '.join(sorted(missing)))
        calls.append({'id': 'call_' + uuid.uuid4().hex, 'type': 'function',
                      'function': {'name': name, 'arguments': json.dumps(arguments)}})
    return {'role': 'assistant', 'content': residue.strip(),
            'reasoning_content': reasoning, 'tool_calls': calls}
