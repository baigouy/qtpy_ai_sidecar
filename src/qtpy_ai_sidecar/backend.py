"""OpenAI-compatible streaming transport, including LM Studio and llama.cpp."""
import asyncio
import contextlib
import json
import os
import time
import httpx


class GenerationTimeout(RuntimeError):
    pass


class TextOnlyToolCall(RuntimeError):
    """Asked for a text-only answer (tools disabled), the model still called a
    tool. Nothing is executed; the caller may ask again or fall back."""


class EmptyModelReply(RuntimeError):
    pass


class RawToolMarkup(RuntimeError):
    """The reply wrote a tool call as text (<tool_call>...): with the tools turned
    off after a loop, a 27B kept doing that and the chat showed an empty answer
    (9 of 11 empty replies, live replay 2026-11-15). Nothing of it is executed."""


class ContextFull(ValueError):
    """The server stopped a reply because prompt + reply filled its context window."""


class OutputLimitReached(RuntimeError):
    """One reply needed more than the output limit; nothing of it was executed."""
    def __init__(self, message, limit):
        super().__init__(message)
        self.limit = limit


RATE_LIMIT_RETRIES = 3
SERVER_RETRIES = 5                       # ~60 s in all for a provider's 5xx outage
SERVER_ERRORS = (500, 502, 503, 504)


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


@contextlib.asynccontextmanager
async def connect_stream(client, url, payload, headers, emit):
    """client.stream('POST', …), retried when the connection cannot be opened
    (a Mistral ConnectTimeout lost a whole request, 2026-11-03): nothing reached
    the server, so sending again is safe. Errors after connecting are not retried."""
    for attempt in range(SERVER_RETRIES + 1):
        try:
            manager = client.stream('POST', url, json=payload, headers=headers)
            response = await manager.__aenter__()
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            if attempt >= SERVER_RETRIES:
                raise
            wait = min(30.0, 2.0 * 2 ** attempt)
            emit('status', f'Could not reach the provider ({type(exc).__name__}); retrying in {wait:.0f} s')
            await asyncio.sleep(wait)
            continue
        try:
            yield response
        except BaseException as exc:
            await manager.__aexit__(type(exc), exc, exc.__traceback__)
            raise
        else:
            await manager.__aexit__(None, None, None)
        return


def content_parts(content):
    """(text, thinking) of a streamed delta's content: a string for most
    servers; Mistral sends a list of typed chunks instead, such as
    {'type': 'text', 'text': …} and {'type': 'thinking', 'thinking': [chunks]}
    (mistral-large-4, 2026-11-03)."""
    if not isinstance(content, list):
        return content or '', ''
    text, thinking = '', ''
    for part in content:
        if not isinstance(part, dict):
            text += str(part)
        elif part.get('type') == 'thinking':
            thinking += content_parts(part.get('thinking'))[0]
        elif part.get('type') == 'text':
            text += part.get('text') or ''
    return text, thinking


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


# notes the host re-sends every turn / step with the same words: kept in the leading system
# message, which then stays the same from one request to the next
_SESSION_NOTES = ('Connected application MCP guidance', '[ACTION_MODE]', '[VISION]')
HOST_NOTE = '[Host note, from the application, not the user]\n'


def _with_note(message, note):
    """*message* with *note* added at the end of its content (text or a list of parts)."""
    content = message.get('content')
    if isinstance(content, list):
        return dict(message, content=list(content) + [{'type': 'text', 'text': '\n\n' + HOST_NOTE + note}])
    return dict(message, content=(content or '') + '\n\n' + HOST_NOTE + note)


def cache_friendly(messages):
    """One leading system message, as local chat templates require, WITHOUT changing the
    start of the prompt from one request to the next: llama.cpp reuses the part of the
    prompt it has already read only up to the first difference. All system messages used
    to be merged into the leading one, so the per-turn host state changed the very start
    and every turn re-read the whole conversation (replay 2026-11-20: 234 of 712 calls,
    78 of 104 min of prompt processing). Now:
      * the first system message and the notes repeated with the same words every turn
        (tool guidance, action mode, vision) make the leading system message;
      * any other system note (the turn's host state, a human action...) is added to the
        message before it, which never changes afterwards;
      * notes after the last message (one-request nudges) are added to the last message."""
    if not messages:
        return []
    head = [messages[0]['content']] if messages[0]['role'] == 'system' else []
    rest = messages[1:] if messages[0]['role'] == 'system' else list(messages)
    session = {}
    out = []
    pending = []           # notes after an assistant reply: they go with the next message
    for m in rest:
        if m['role'] != 'system':
            if pending and m['role'] in ('user', 'tool'):
                m = _with_note(m, '\n\n'.join(pending))
                pending = []
            out.append(m)
            continue
        text = m['content'] if isinstance(m['content'], str) else str(m['content'])
        if text.startswith(_SESSION_NOTES):
            session[text.split('\n', 1)[0][:40]] = text        # the latest of each kind
        elif out and out[-1]['role'] in ('user', 'tool'):
            out[-1] = _with_note(out[-1], text)
        elif out:
            pending.append(text)
        else:
            head.append(text)
    if pending:
        out.append({'role': 'user', 'content': HOST_NOTE + '\n\n'.join(pending)})
    head += [session[k] for k in sorted(session)]
    transport = [{'role': 'system', 'content': '\n\n'.join(head)}] if head else []
    return transport + out


def cache_key(messages):
    """The label of a conversation for the provider's prompt cache (OpenAI, Mistral:
    `prompt_cache_key`), the same for every request of it: a hash of its first system and
    first user message, so nothing of the conversation itself is sent in it."""
    import hashlib
    first = next((m for m in messages if m['role'] == 'system'), {}).get('content')
    user = next((m for m in messages if m['role'] == 'user'), {}).get('content')
    text = json.dumps([first, user], sort_keys=True, default=str)
    return 'qtpy-sidecar-' + hashlib.sha256(text.encode('utf-8', 'replace')).hexdigest()[:24]


EPHEMERAL = {'type': 'ephemeral'}


def _marked(message):
    """*message* with a cache mark on its last content part (a string becomes one text part)."""
    content = message.get('content')
    if isinstance(content, str):
        parts = [{'type': 'text', 'text': content}] if content else []
    else:
        parts = [dict(p) for p in content or []]
    if not parts:
        return message
    parts[-1]['cache_control'] = EPHEMERAL
    return dict(message, content=parts)


def mark_cache_points(transport, model):
    """OpenRouter passes Claude's and Gemini's prompt caching through only with explicit
    marks (`cache_control` on a content part): the leading system message (the tools come
    before it, so they are cached with it), and for Claude also the last user / tool
    message, so each request reads the whole conversation before it from the cache.
    Other models there cache by themselves."""
    name = (model or '').lower()
    claude, gemini = name.startswith('anthropic/'), name.startswith('google/gemini')
    if not (claude or gemini) or not transport:
        return transport
    out = list(transport)
    if out[0]['role'] == 'system':
        out[0] = _marked(out[0])
    if claude and len(out) > 1 and out[-1]['role'] in ('user', 'tool'):
        out[-1] = _marked(out[-1])
    return out


def with_cached_tokens(usage):
    """*usage* with `cached_tokens`: the prompt tokens the provider read from its cache
    (OpenAI / Mistral / OpenRouter: prompt_tokens_details.cached_tokens; llama.cpp:
    prompt_tokens_details too, when it reports it)."""
    if not isinstance(usage, dict):
        return usage
    cached = (usage.get('prompt_tokens_details') or {}).get('cached_tokens')
    if isinstance(cached, int):
        usage = dict(usage, cached_tokens=cached)
    return usage


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
        # One leading system message (many local templates require it), and the start of the
        # prompt the same from request to request: llama.cpp and the providers' prompt caches
        # reuse what was already read only up to the first difference (all system messages
        # used to be merged at the front, so the per-turn host state broke every cache)
        transport = cache_friendly(messages)
        payload = dict(model=self.config.model, messages=transport, stream=True,
                       max_tokens=max_tokens or self.config.output_tokens, temperature=0.2,
                       stream_options={'include_usage': True})
        if self.config.provider in ('openai', 'mistral'):
            # routes the conversation's requests to the same cache (cached input: 10 % of the price)
            payload['prompt_cache_key'] = cache_key(messages)
        if self.config.provider == 'openai':
            payload['max_completion_tokens'] = payload.pop('max_tokens')
            payload.pop('temperature')
            payload['store'] = False
        elif self.config.provider == 'openrouter':
            headers['X-Title'] = 'QtPy AI Sidecar'
            payload.pop('temperature')
            payload['messages'] = transport = mark_cache_points(transport, self.config.model)
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
              for attempt in range(SERVER_RETRIES + 1):
                async with connect_stream(client, base_url.rstrip('/') + '/chat/completions',
                                          payload, headers, emit) as response:
                    if response.status_code in SERVER_ERRORS and attempt < SERVER_RETRIES:
                        # the provider's server briefly unreachable (Mistral answered 503
                        # "upstream connect error" for ~25 s, 2026-11-03): nothing ran, so
                        # the same request is sent again after 2, 4, 8, 16, 30 s
                        wait = min(30.0, 2.0 * 2 ** attempt)
                        await response.aread()
                        emit('status', f'The provider answered HTTP {response.status_code}; retrying in {wait:.0f} s')
                        await asyncio.sleep(wait)
                        continue
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
                        if (response.status_code in (400, 422) and 'prompt_cache_key' in payload
                                and 'prompt_cache_key' in detail and attempt < SERVER_RETRIES):
                            # a server that does not take the cache label: the same request without it
                            payload.pop('prompt_cache_key')
                            continue
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
                            addition, thought = content_parts(delta.get('content'))
                            text += addition
                            reasoning += (delta.get('reasoning_content') or '') + thought
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
                limit = max_tokens or self.config.output_tokens
                written = (usage or {}).get('completion_tokens')
                if isinstance(written, int) and written < 0.9 * limit:
                    # stopped after 55 tokens of 8,192: the server's context was full, not the
                    # output limit (Qwen3.8-27B, llama.cpp -c 65536, 2026-11-15; the chat said
                    # "one step may use at most 8,192 tokens" and "Continue" did nothing)
                    prompt = (usage or {}).get('prompt_tokens')
                    raise ContextFull(f'The conversation filled the model\'s context ({prompt} + {written} tokens'
                                      f' of {self.config.context_tokens}). No partial tool call executed. Use Compress.')
                raise OutputLimitReached(f'Model reached its {limit}-token output limit. No partial tool call executed. Earlier edits may remain.', limit)
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
                raise RawToolMarkup('Model emitted raw tool markup instead of structured tool calls. Check the server chat template; no markup executed.')
            if final_only and calls:
                raise TextOnlyToolCall('Text-only recovery returned a tool call; nothing executed')
            message = {'role': 'assistant', 'content': text}
            if raw_qwen and reasoning:
                message['reasoning_content'] = reasoning
            if calls:
                message['tool_calls'] = [calls[i] for i in sorted(calls)]
            return message, with_cached_tokens(usage)
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
