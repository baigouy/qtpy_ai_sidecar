"""OpenAI-compatible streaming transport, including LM Studio and llama.cpp."""
import asyncio
import json
import os
import time
import httpx


class GenerationTimeout(RuntimeError):
    pass


class EmptyModelReply(RuntimeError):
    pass


RATE_LIMIT_RETRIES = 3


def per_minute_limit_message(detail):
    """Plain words for an account quota that waiting a few seconds does not
    lift: a request larger than the tokens-per-minute quota (a free tier
    allowed 7,000 input tokens per minute, less than one turn with an
    application's tools), or the free models' daily request quota."""
    import re
    if re.search(r'only available on agentic harnesses|Gate Free Endpoints', detail, re.I):
        return ('This free model is reserved by the provider for the apps on its approved list, which this chat '
                'is not on. Choose another free model in the connection settings (plug icon), such as '
                'openrouter/free.')
    if re.search(r'free-models-per-day|per[- ]day', detail, re.I) and re.search(r'rate limit', detail, re.I):
        return ('The free daily request quota of this provider is used up, so nothing can be sent until it resets. '
                'Each chat message makes several requests (one per tool step). Add credit with this provider for '
                'a larger quota, or use another provider or a local model.')
    found = re.search(r'tokens per minute[^:]*:\s*Limit\s*(\d+),\s*Requested\s*(\d+)', detail, re.I)
    if not found:
        return None
    limit, requested = found.groups()
    return (f'This message needs {requested} input tokens, but your plan with this provider allows only {limit} '
            f'per minute, so it cannot be sent (waiting does not help). This is a limit of the account, not of '
            f'the model or of the context setting: use a paid tier with this provider, another provider, or a local model.')


def rate_limit_wait(headers, attempt):
    """Seconds to wait after an HTTP 429: the provider's Retry-After (or an
    x-ratelimit-reset-tokens such as '7.66s'), else 2, 4, 8 s; at most 30."""
    for name in ('retry-after', 'x-ratelimit-reset-tokens', 'x-ratelimit-reset-requests'):
        value = str(headers.get(name) or '').strip()
        try:
            if value.endswith('ms'):
                return min(30.0, max(0.5, float(value[:-2]) / 1000))
            return min(30.0, max(0.5, float(value.rstrip('s'))))
        except ValueError:
            continue
    return min(30.0, 2.0 * 2 ** attempt)


def apply_reasoning_strength(transport, config, final_only, emit):
    """Strength-only templates ignore enable_thinking and reasoning_effort; they read a system
    line instead. 'Off' cannot be honoured there, so it becomes the lowest strength."""
    level = 'low' if final_only or config.thinking == 'disabled' else config.thinking_strength
    if level == 'default':
        return
    if config.thinking == 'disabled' and not final_only:
        emit('status', 'This model cannot switch reasoning off; using Reasoning strength: low')
    line = f'Reasoning strength: {level}.'
    if transport and transport[0]['role'] == 'system':
        transport[0] = {'role': 'system', 'content': transport[0]['content'] + '\n\n' + line}
    else:
        transport.insert(0, {'role': 'system', 'content': line})


class ModelClient:
    def __init__(self, config, secret_sink=lambda value: None):
        self.config = config
        self.secret_sink = secret_sink
        from .runtime import OwnedLlama
        self.runtime = OwnedLlama(config) if config.runtime else None

    async def complete(self, messages, tools, cancel, emit, max_tokens=None, final_only=False):
        headers = {}
        base_url = self.config.base_url
        if self.config.provider == 'local' and not self.runtime:
            raise ValueError('Choose a GGUF model and llama-server in Model Library before sending. Local mode uses the sidecar-managed runtime.')
        if self.config.provider == 'anthropic':
            from .anthropic_backend import complete
            return await complete(self.config, messages, tools, cancel, emit, max_tokens, self.secret_sink)
        if self.runtime:
            url, key = await self.runtime.ensure(cancel, emit)
            base_url = url + '/v1'
            headers['Authorization'] = 'Bearer ' + key
            self.secret_sink(key)
        elif self.config.api_key_env or self.config.provider != 'local':
            from .credentials import get_key
            key = get_key(self.config)
            self.secret_sink(key)
            if key:
                headers['Authorization'] = 'Bearer ' + key
        # Many local templates require one leading system message.
        systems = [m['content'] for m in messages if m['role'] == 'system']
        transport = ([{'role': 'system', 'content': '\n\n'.join(systems)}] if systems else [])
        transport += [m for m in messages if m['role'] != 'system']
        payload = dict(model=self.config.model, messages=transport, stream=True,
                       max_tokens=max_tokens or self.config.output_tokens, temperature=0.2,
                       stream_options={'include_usage': True})
        if self.config.provider == 'openai':
            payload['max_completion_tokens'] = payload.pop('max_tokens')
            payload.pop('temperature')
            payload['store'] = False
        elif self.config.provider == 'openrouter':
            headers['X-Title'] = 'QtPy AI Sidecar'
            payload.pop('temperature')
        elif self.config.provider == 'groq':
            # reasoning stays out of the reply text (Qwen would otherwise put <think> in it);
            # gpt-oss models take include_reasoning instead
            if self.config.model.startswith('openai/gpt-oss'):
                payload['include_reasoning'] = False
            else:
                payload['reasoning_format'] = 'hidden'
        elif self.config.provider == 'mistral':
            # stream_options is not among the request fields Mistral documents (2026-11-03)
            payload.pop('stream_options')
        if tools:
            payload['tools'] = tools
            payload['parallel_tool_calls'] = False
        if self.config.thinking_backend == 'llama_cpp':
            if self.config.thinking != 'default':
                payload['chat_template_kwargs'] = {'enable_thinking': self.config.thinking == 'enabled'}
            if self.config.thinking == 'disabled':
                payload['reasoning_effort'] = 'none'
            elif self.config.thinking_strength != 'default':
                payload['reasoning_effort'] = self.config.thinking_strength
        elif self.config.thinking_backend == 'reasoning_effort':
            if self.config.thinking == 'disabled':
                payload['reasoning_effort'] = 'none'
            elif self.config.thinking_strength != 'default':
                payload['reasoning_effort'] = self.config.thinking_strength
            if self.config.provider == 'iteracompute' and self.config.thinking != 'disabled':
                # its models list says Qwen3.8 thinks at 'xhigh' by default: a short chat reply then
                # took 30-120 s (2026-11-03). It offers low/medium/xhigh, so high means xhigh.
                payload['reasoning_effort'] = {'default': 'low', 'high': 'xhigh'}.get(
                    self.config.thinking_strength, self.config.thinking_strength)
        if final_only and self.config.thinking_backend == 'llama_cpp':
            payload['chat_template_kwargs'] = {'enable_thinking': False}
            payload['reasoning_effort'] = 'none'
        if self.config.thinking_backend == 'llama_cpp' and getattr(self.runtime, 'reasoning_control', None) == 'strength':
            apply_reasoning_strength(transport, self.config, final_only, emit)
        progress = {'first_sse_seconds': None, 'stream_events': 0,
                    'content_characters': 0, 'reasoning_characters': 0,
                    'tool_argument_characters': 0}
        async def generate():
            text, reasoning, calls, finish, usage = '', '', {}, None, {}
            timeout = httpx.Timeout(connect=15, read=180, write=30, pool=15)
            async with httpx.AsyncClient(timeout=timeout) as client:
              for attempt in range(RATE_LIMIT_RETRIES + 1):
                async with client.stream('POST', base_url.rstrip('/') + '/chat/completions',
                                         json=payload, headers=headers) as response:
                    if response.status_code == 429 and attempt < RATE_LIMIT_RETRIES:
                        # a cloud rate limit (tokens per minute): wait as told, then retry
                        wait = rate_limit_wait(response.headers, attempt)
                        detail = (await response.aread()).decode(errors='replace')[:1500]
                        if per_minute_limit_message(detail):      # an account quota: retrying is useless
                            raise RuntimeError(per_minute_limit_message(detail))
                        emit('status', f'Rate limited by the provider; retrying in {wait:.0f} s')
                        await asyncio.sleep(wait)
                        continue
                    if response.status_code >= 400:
                        detail = (await response.aread()).decode(errors='replace')[:1500]
                        raise RuntimeError(per_minute_limit_message(detail) or f'Model HTTP {response.status_code}: {detail}')
                    async for line in response.aiter_lines():
                        if not line.startswith('data:'):
                            continue
                        data = line[5:].strip()
                        if data == '[DONE]':
                            break
                        chunk = json.loads(data)
                        progress['stream_events'] += 1
                        if progress['first_sse_seconds'] is None:
                            progress['first_sse_seconds'] = time.monotonic() - started
                        usage = chunk.get('usage') or usage
                        choices = chunk.get('choices') or []
                        if choices:
                            choice = choices[0]
                            finish = choice.get('finish_reason') or finish
                            delta = choice.get('delta') or {}
                            addition = delta.get('content') or ''
                            text += addition
                            reasoning += delta.get('reasoning_content') or ''
                            for part in delta.get('tool_calls') or []:
                                item = calls.setdefault(part['index'], {'id': '', 'type': 'function',
                                    'function': {'name': '', 'arguments': ''}})
                                item['id'] += part.get('id') or ''
                                for key in ('name', 'arguments'):
                                    item['function'][key] += (part.get('function') or {}).get(key) or ''
                        progress.update(content_characters=len(text), reasoning_characters=len(reasoning),
                                        tool_argument_characters=sum(len(c['function']['arguments']) for c in calls.values()))
                        emit('generation', {'characters': len(text) + len(reasoning), 'usage': usage})
                break
            if finish is None:
                raise RuntimeError('Incomplete model stream; no partial tool call executed')
            if finish == 'length':
                raise RuntimeError(f'Model reached its {max_tokens or self.config.output_tokens}-token output limit. No partial tool call executed. Earlier edits may remain.')
            raw_qwen = self.runtime is not None and self.runtime.raw_qwen
            if raw_qwen:
                if calls:
                    raise RuntimeError('Mixed raw/native Qwen calls; nothing executed')
                from .qwen_protocol import parse_reply
                schemas = {t['function']['name']: t['function']['parameters'] for t in tools}
                thinking = payload.get('chat_template_kwargs', {}).get('enable_thinking') is not False
                parsed = parse_reply(text, schemas, require_think_end=thinking)
                text = parsed['content']
                reasoning = parsed['reasoning_content']
                calls = {i: call for i, call in enumerate(parsed['tool_calls'])}
            if not text and not calls:
                raise EmptyModelReply('Model returned no final reply or tool calls; earlier edits may remain')
            if '<tool_call>' in text and not calls:
                raise RuntimeError('Model emitted raw tool markup instead of structured tool calls. Check the server chat template; no markup executed.')
            if final_only and calls:
                raise RuntimeError('Text-only recovery returned a tool call; nothing executed')
            message = {'role': 'assistant', 'content': text}
            if raw_qwen and reasoning:
                message['reasoning_content'] = reasoning
            if calls:
                message['tool_calls'] = [calls[i] for i in sorted(calls)]
            return message, usage
        started = time.monotonic()
        timeout = min(self.config.generation_timeout_seconds, getattr(self.config, "response_timeout_s", 30)) if final_only else self.config.generation_timeout_seconds
        task = asyncio.create_task(generate())
        try:
            while not task.done():
                if time.monotonic() - started > timeout:
                    emit('generation_timeout', {
                        **progress, 'final_only': bool(final_only),
                        'configured_timeout_seconds': self.config.generation_timeout_seconds,
                        'response_timeout_s': getattr(self.config, 'response_timeout_s', 30),
                        'effective_timeout_seconds': timeout,
                        'elapsed_seconds_before_cleanup': time.monotonic() - started,
                        'advertised_tools': len(tools),
                        'prompt_characters': len(json.dumps(payload.get('messages', []))),
                        'tool_schema_characters': len(json.dumps(payload.get('tools', [])))})
                    task.cancel()
                    raise GenerationTimeout(f'Model response exceeded {timeout}s. No partial tool call executed; completed edits remain.')
                if cancel.is_set():
                    task.cancel()
                    raise InterruptedError('Generation stopped; inspect completed edits before continuing')
                await asyncio.sleep(.1)
            return await task
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    def close(self):
        if self.runtime:
            self.runtime.stop()
