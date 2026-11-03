"""Claude Messages streaming with native tool-use and signed thinking preservation."""
import asyncio
import json
import time
import httpx
from .credentials import get_key
from .backend import (SERVER_RETRIES, SERVER_ERRORS, RATE_LIMIT_RETRIES, connect_stream,
                      rate_limit_wait, per_minute_limit_message)


def _anthropic_part(part):
    """An OpenAI-style content part (text, or image_url with a data URL) as a
    Claude Messages block."""
    if part.get('type') == 'image_url':
        header, data = part['image_url']['url'].split(',', 1)
        mime = header[len('data:'):].split(';', 1)[0]
        return {'type': 'image', 'source': {'type': 'base64', 'media_type': mime, 'data': data}}
    return {'type': 'text', 'text': part.get('text', '')}


def convert_messages(messages):
    system = '\n\n'.join(m['content'] for m in messages if m['role'] == 'system')
    converted = []
    for message in messages:
        role = message['role']
        if role == 'system':
            continue
        if role == 'tool':
            role, content = 'user', [{'type': 'tool_result', 'tool_use_id': message['tool_call_id'], 'content': message['content']}]
        elif role == 'assistant' and message.get('_anthropic_blocks'):
            content = message['_anthropic_blocks']
        elif isinstance(message.get('content'), list):
            content = [_anthropic_part(p) for p in message['content']]     # an attached image
        else:
            content = [{'type': 'text', 'text': message['content']}] if message.get('content') else []
            for call in message.get('tool_calls', []):
                content.append({'type': 'tool_use', 'id': call['id'], 'name': call['function']['name'],
                                'input': json.loads(call['function']['arguments'])})
        if not content:
            continue
        if converted and converted[-1]['role'] == role:
            converted[-1]['content'].extend(content)
        else:
            converted.append({'role': role, 'content': content})
    return system, converted


async def complete(config, messages, tools, cancel, emit, max_tokens, secret_sink):
    key = get_key(config)
    secret_sink(key)
    system, converted = convert_messages(messages)
    output = max_tokens or config.output_tokens
    payload = dict(model=config.model, max_tokens=output, system=system, messages=converted, stream=True)
    if tools:
        payload['tools'] = [{'name': t['function']['name'], 'description': t['function'].get('description', ''),
                             'input_schema': t['function']['parameters']} for t in tools]
    if config.thinking == 'disabled':
        payload['thinking'] = {'type': 'disabled'}
    elif config.thinking == 'enabled':
        if config.thinking_backend == 'anthropic_adaptive':
            payload['thinking'] = {'type': 'adaptive'}
            if config.thinking_strength != 'default':
                payload['output_config'] = {'effort': config.thinking_strength}
        elif config.thinking_backend == 'anthropic_budget':
            requested = config.thinking_budget if config.thinking_budget >= 0 else {'low': 1024, 'medium': 4096, 'high': 8192, 'default': 2048}[config.thinking_strength]
            if output <= 1024:
                raise ValueError('Claude manual thinking needs output greater than 1024 tokens')
            payload['thinking'] = {'type': 'enabled', 'budget_tokens': max(1024, min(requested, output - 512))}
        else:
            raise ValueError('Choose a Claude thinking capability compatible with the selected model')
    async def generate():
        blocks, fragments, usage, finish, stopped, chars = {}, {}, {}, None, False, 0
        headers = {'x-api-key': key, 'anthropic-version': '2023-06-01'}
        async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=15)) as client:
            for attempt in range(SERVER_RETRIES + 1):
              # same retries as the other providers: a connection that cannot open,
              # a server outage (5xx, Claude's 529 "overloaded") and a short rate limit
              async with connect_stream(client, config.base_url.rstrip('/') + '/messages', payload, headers, emit) as response:
                if response.status_code in SERVER_ERRORS + (529,) and attempt < SERVER_RETRIES:
                    wait = min(30.0, 2.0 * 2 ** attempt)
                    await response.aread()
                    emit('status', f'The provider answered HTTP {response.status_code}; retrying in {wait:.0f} s')
                    await asyncio.sleep(wait)
                    continue
                if response.status_code == 429 and attempt < RATE_LIMIT_RETRIES:
                    wait = rate_limit_wait(response.headers, attempt)
                    detail = (await response.aread()).decode(errors='replace')[:1500]
                    if per_minute_limit_message(detail):      # an account quota: retrying is useless
                        raise RuntimeError(per_minute_limit_message(detail))
                    emit('status', f'Rate limited by the provider; retrying in {wait:.0f} s')
                    await asyncio.sleep(wait)
                    continue
                if response.status_code >= 400:
                    detail = (await response.aread()).decode(errors='replace')[:1500]
                    raise RuntimeError(f'Claude HTTP {response.status_code}: {detail}')
                async for line in response.aiter_lines():
                    if not line.startswith('data:'):
                        continue
                    event = json.loads(line[5:].strip())
                    kind = event['type']
                    if kind == 'error':
                        raise RuntimeError('Claude stream error: ' + str(event.get('error')))
                    if kind == 'message_start':
                        usage.update(event['message'].get('usage', {}))
                    elif kind == 'content_block_start':
                        blocks[event['index']] = dict(event['content_block'])
                    elif kind == 'content_block_delta':
                        index, delta = event['index'], event['delta']
                        block = blocks[index]
                        if delta['type'] == 'input_json_delta':
                            fragments[index] = fragments.get(index, '') + delta['partial_json']
                        else:
                            field = {'text_delta': 'text', 'thinking_delta': 'thinking', 'signature_delta': 'signature'}.get(delta['type'])
                            if field:
                                block[field] = block.get(field, '') + delta[field]
                                chars += len(delta[field]) if field != 'signature' else 0
                        emit('generation', {'characters': chars, 'usage': usage})
                    elif kind == 'content_block_stop':
                        index = event['index']
                        if index in fragments:
                            blocks[index]['input'] = json.loads(fragments[index] or '{}')
                    elif kind == 'message_delta':
                        finish = event['delta'].get('stop_reason') or finish
                        usage.update(event.get('usage', {}))
                    elif kind == 'message_stop':
                        stopped = True
                        break
              break
        if not stopped or not finish:
            raise RuntimeError('Incomplete Claude response; no partial tool call executed')
        if finish not in ('end_turn', 'tool_use', 'stop_sequence'):
            raise RuntimeError('Claude stopped with ' + finish + '; no partial tool call executed. Earlier edits may remain.')
        content = [blocks[i] for i in sorted(blocks)]
        answer = {'role': 'assistant', 'content': '\n'.join(b.get('text', '') for b in content if b['type'] == 'text'), '_anthropic_blocks': content}
        calls = [{'id': b['id'], 'type': 'function', 'function': {'name': b['name'], 'arguments': json.dumps(b['input'])}}
                 for b in content if b['type'] == 'tool_use']
        if calls:
            answer['tool_calls'] = calls
        if not answer['content'] and not calls:
            raise RuntimeError('Claude returned no text or tool call')
        return answer, usage
    from .backend import GenerationTimeout
    started = time.monotonic()
    task = asyncio.create_task(generate())
    try:
        while not task.done():
            if time.monotonic() - started > config.generation_timeout_seconds:
                task.cancel()
                raise GenerationTimeout('Claude response time limit reached; no partial tool call executed.')
            if cancel.is_set():
                task.cancel()
                raise InterruptedError('Claude generation stopped; completed edits may remain')
            await asyncio.sleep(.1)
        return await task
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
