"""2026-11-19 replay fixes: the application's rules for a request's topics go WITH the
request; a repeated read says what to do next; a letter edit is not refused on a
selection the model has since cleared."""
import pytest

from qtpy_ai_sidecar.adapters.pyfigures import PyFiguresAdapter


def _adapter(tmp_path, answers):
    adapter = PyFiguresAdapter(tmp_path / 'bridge.json')
    calls = []

    def request(operation, arguments=None):
        calls.append((operation, arguments))
        return answers[operation](arguments) if callable(answers[operation]) else answers[operation]
    adapter.request = request
    return adapter, calls


def test_the_rules_of_the_request_go_with_it(tmp_path):
    adapter, calls = _adapter(tmp_path, {'request_rules': {'rules': 'ROIs: detect_objects in one call.'}})
    adapter.current_request = ('draw ROIs over every cell in e', 'segment c')
    text = adapter.context_instructions({'selection': {}})
    assert text.endswith('RULES FOR THIS REQUEST (follow them; no search needed to learn them): '
                         'ROIs: detect_objects in one call.')
    assert calls == [('request_rules', {'text': 'draw ROIs over every cell in e', 'earlier': 'segment c'})]


def test_nothing_is_added_when_no_rule_fits_or_the_app_is_older(tmp_path):
    adapter, _ = _adapter(tmp_path, {'request_rules': {'rules': ''}})
    adapter.current_request = ('thanks', '')
    plain = adapter._context_instructions({'selection': {}})
    assert adapter.context_instructions({'selection': {}}) == plain

    def older(arguments):
        raise RuntimeError('Unknown operation')
    adapter, _ = _adapter(tmp_path, {'request_rules': older})
    adapter.current_request = ('add scale bars', '')
    assert adapter.context_instructions({'selection': {}}) == plain
    adapter, calls = _adapter(tmp_path, {})
    assert adapter.context_instructions({'selection': {}}) == plain and calls == []     # no request yet


def test_a_repeated_read_says_what_to_do_next():
    from qtpy_ai_sidecar.read_cache import NOTICE
    assert 'answer from it' in NOTICE and 'Do not read it again' in NOTICE and 'search for it' in NOTICE


def test_a_cleared_selection_no_longer_limits_a_letter_edit(tmp_path):
    state = {'selection': {'selected_panels': [{'panel_id': '0/1'}]}}
    edit = {'tool_name': 'edit_panel_letters', 'arguments': {'action': 'style', 'bold': False, 'scope': 'all'}}
    adapter, _ = _adapter(tmp_path, {'inspect': {'selection': {'selected_panels': []}}})
    adapter.validate_tool_call('use_pyfigures_tool', edit, state, "and don't make it bold neither")
    adapter, _ = _adapter(tmp_path, {'inspect': {'selection': {'selected_panels': [{'panel_id': '0/1'}]}}})
    with pytest.raises(ValueError, match='only panel 0/1'):
        adapter.validate_tool_call('use_pyfigures_tool', edit, state, "and don't make it bold neither")


def test_the_engine_hands_the_request_and_the_one_before_to_the_adapter(tmp_path):
    import asyncio
    from qtpy_ai_sidecar.adapters import NullAdapter
    from qtpy_ai_sidecar.config import Config
    from qtpy_ai_sidecar.engine import Engine

    class Model:
        async def complete(self, messages, tools, cancel, emit, max_tokens=None):
            self.seen = messages
            return {'role': 'assistant', 'content': 'Done.'}, {}

    class Adapter(NullAdapter):
        current_request = ('', '')
        got = []

        def context_instructions(self, state):
            self.got.append(self.current_request)
            return 'RULES FOR THIS REQUEST: ' + self.current_request[0]
    model, adapter = Model(), Adapter()
    engine = Engine(Config(application='test', state_dir=str(tmp_path / 'state')), adapter, backend=model)
    asyncio.run(engine.turn('draw ROIs over every cell in e', lambda *a: None))
    asyncio.run(engine.turn('you did not finish', lambda *a: None))
    assert adapter.got == [('draw ROIs over every cell in e', ''), ('you did not finish', 'draw ROIs over every cell in e')]
    host = next(m['content'] for m in model.seen if m['content'].startswith('[CURRENT_HOST_STATE]'))
    assert 'RULES FOR THIS REQUEST: you did not finish' in host


@pytest.mark.parametrize('text', ['let me edit the b crop', "let me edit b's crop", 'let me edit the crop of b',
                                  'I want to adjust the crop in b myself'])
def test_let_me_edit_the_b_crop_opens_b_on_its_crop_tab_not_the_selected_panel(tmp_path, text):
    """User 2026-11-19 ("I love this feature, find a way it cannot be lost"): "let me edit
    the b crop" opened the editor of the SELECTED panel, g. The panel the words name wins
    over the selection, and the editor opens on the tab of the thing named."""
    state = {'selection': {'selected_panels': [{'panel_id': '2/0'}]},
             'panel_references': [{'panel_id': f'0/{i}', 'letters': [l]} for i, l in enumerate('abcdefg')]
             + [{'panel_id': '2/0', 'letters': ['g']}]}
    opened = []
    adapter, _ = _adapter(tmp_path, {'inspect': state,
                                     'open_annotation_editor': lambda args: opened.append(args) or {'status': 'ok'}})
    out = adapter._open_editor_for_self_edit(text)
    assert opened == [{'panel_ref': 'b', 'tab': 'crop'}], (text, opened)
    assert 'panel **b**' in out['content'] and 'Rotate + Crop' in out['content']
