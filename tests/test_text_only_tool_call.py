"""2026-11-06 (PyFigures, Mistral Large 4): after eight tool searches the turn
was stopped and the model asked for a text-only explanation, but it answered
with another tool call; the turn ended on "Text-only recovery returned a tool
call". It is now asked once more, then given a plain fallback answer."""
import asyncio

from qtpy_ai_sidecar.backend import TextOnlyToolCall
from qtpy_ai_sidecar.config import Config
from qtpy_ai_sidecar.engine import Engine


def _engine(tmp_path, replies, error=TextOnlyToolCall):
    class Model:
        calls = []

        async def complete(self, messages, tools, cancel, emit, final_only=False):
            assert tools == [] and final_only
            self.calls.append(messages)
            r = replies[len(self.calls) - 1]
            if r is None:
                raise error('Text-only recovery returned a tool call; nothing executed')
            return {'role': 'assistant', 'content': r}, {}
    model = Model()
    return Engine(Config(state_dir=str(tmp_path)), backend=model, hub_factory=lambda *a: None), model


def test_a_tool_call_is_asked_again_in_plain_text(tmp_path):
    engine, model = _engine(tmp_path, [None, 'The letters are now outside the rows.'])
    out = asyncio.run(engine._stopped_text_summary([{'role': 'user', 'content': 'x'}], lambda *e: None))
    assert out['content'] == 'The letters are now outside the rows.'
    assert len(model.calls) == 2 and 'plain text only' in model.calls[1][-1]['content']


def test_two_tool_calls_give_a_plain_fallback(tmp_path):
    engine, model = _engine(tmp_path, [None, None])
    out = asyncio.run(engine._stopped_text_summary([{'role': 'user', 'content': 'x'}], lambda *e: None))
    assert 'No further tool was run' in out['content'] and not out.get('tool_calls')


def test_a_tool_call_written_as_text_is_handled_alike(tmp_path):
    """Qwen3.8-27B wrote <tool_call> as text after the tools were stopped: the turn
    ended with an empty answer (live replay with vision, 2026-11-16)."""
    from qtpy_ai_sidecar.backend import RawToolMarkup
    engine, model = _engine(tmp_path, [None, 'Panel j was not cropped: tell me the margins.'], RawToolMarkup)
    out = asyncio.run(engine._stopped_text_summary([{'role': 'user', 'content': 'x'}], lambda *e: None))
    assert out['content'].startswith('Panel j was not cropped')
    engine, model = _engine(tmp_path, [None, None], RawToolMarkup)
    out = asyncio.run(engine._stopped_text_summary([{'role': 'user', 'content': 'x'}], lambda *e: None))
    assert 'No further tool was run' in out['content']
