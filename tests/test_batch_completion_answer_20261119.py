"""2026-11-19 (user, live app): "create a fig with the first 20 files", the chat asked
"data plot or table panel?", the user said "data plot", and the turn ended after the
first batch of 6 images with "Done: add image (group_path=[]) on 6 items": the short
answer looked like a whole one-step instruction. The work is the request before it."""
import json

from qtpy_ai_sidecar.adapters.pyfigures import PyFiguresAdapter

ADD = {'tool_name': 'add_image', 'arguments': {'group_path': []},
       'batch': [{'filename': f'C:/data/{i}.tif'} for i in range(6)]}


def _result(total=6):
    return {'is_error': False, 'content': json.dumps({
        'result': f'add_image: {total} of {total} item(s) done in one call', 'batch_done': total,
        'batch_total': total, 'document_changed': True, 'errors': [],
        'verified': 'Each item was applied to the open figure and read back.'})}


def _reply(text, state=None, call=ADD):
    return PyFiguresAdapter('unused').verified_completion('use_pyfigures_tool', call, _result(), state or {}, text)


def test_an_answer_to_a_question_goes_back_to_the_model():
    asked = {'_last_reply': 'Should each table become a data plot or a table panel in the figure?'}
    assert _reply('data plot', asked) is None


def test_a_batch_short_of_the_number_asked_goes_back_to_the_model():
    assert _reply('add the first 20 files of my folder') is None


def test_a_whole_batch_still_answers_at_once_without_where_it_went():
    out = _reply('add these six images')
    assert out and 'group_path' not in out and '[]' not in out
