"""OpenAI-compatible streaming transport, including LM Studio and llama.cpp."""
import asyncio
import json
import os
import httpx


class EmptyModelReply(RuntimeError):
    pass


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
        if final_only and self.config.thinking_backend == 'llama_cpp':
            payload['chat_template_kwargs'] = {'enable_thinking': False}
            payload['reasoning_effort'] = 'none'
        async def generate():
            text, reasoning, calls, finish, usage = '', '', {}, None, {}
            timeout = httpx.Timeout(connect=15, read=180, write=30, pool=15)
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream('POST', base_url.rstrip('/') + '/chat/completions',
                                         json=payload, headers=headers) as response:
                    if response.status_code >= 400:
                        detail = (await response.aread()).decode(errors='replace')[:1500]
                        raise RuntimeError(f'Model HTTP {response.status_code}: {detail}')
                    async for line in response.aiter_lines():
                        if not line.startswith('data:'):
                            continue
                        data = line[5:].strip()
                        if data == '[DONE]':
                            break
                        chunk = json.loads(data)
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
                        emit('generation', {'characters': len(text) + len(reasoning), 'usage': usage})
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
        task = asyncio.create_task(generate())
        try:
            while not task.done():
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
