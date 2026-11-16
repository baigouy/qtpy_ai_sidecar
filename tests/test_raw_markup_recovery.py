"""A tool call written as text (<tool_call>...) is never executed and no longer
ends the turn with an empty answer: the model is asked once for a plain reply
(Qwen3.8-27B, live replay 2026-11-15: 9 of its 11 empty answers)."""
import asyncio

from qtpy_ai_sidecar.backend import RawToolMarkup
from qtpy_ai_sidecar.config import Config
from qtpy_ai_sidecar.engine import Engine

from test_promised_action import Hub


class MarkupWriter:
    def __init__(self):
        self.plain_asked = 0

    async def complete(self, messages, tools, cancel, emit, final_only=False):
        if any(m['role'] == 'system' and 'wrote a tool call as text' in str(m.get('content')) for m in messages):
            self.plain_asked += 1
            return {'role': 'assistant', 'content': 'I could not see the image, so panel j was not cropped. '
                                                    'Click the region, or give the crop margins.'}, {}
        raise RawToolMarkup('Model emitted raw tool markup instead of structured tool calls.')


def test_markup_gets_a_plain_answer_and_nothing_runs(tmp_path):
    hub, model = Hub(), MarkupWriter()
    engine = Engine(Config(state_dir=str(tmp_path)), backend=model, hub_factory=lambda *a: hub)
    events = []
    asyncio.run(engine.turn('in j crop around the 4 nuclei', lambda *a: events.append(a)))
    assert model.plain_asked == 1 and hub.calls == []
    answers = [v for k, v in events if k == 'assistant']
    assert answers and 'not cropped' in answers[-1]
    assert 'raw_markup_recovery' in engine.journal.path.read_text(encoding='utf-8')
