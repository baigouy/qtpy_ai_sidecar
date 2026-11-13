"""Human-style requests through Mistral Large 4 (2026-11-12): guards that
refused what the user had asked for or accepted.
"is it colour blind safe?" -> the assistant proposes magenta and green ->
"fix it": set_lut MAGENTA was refused as "not named by the request"."""
import json

import pytest

from qtpy_ai_sidecar.adapters.pyfigures import PyFiguresAdapter
from qtpy_ai_sidecar.errors import NeedsClarification

PANELS = [{'panel_id': '0/0', 'letters': ['A'], 'channel_colours': ['RED', 'GREEN'], 'luts': [None, None]}]
OFFER = ('Not entirely: panel A shows RED + GREEN. A colour-blind-friendly pair would be '
         'magenta + green, or cyan + yellow. Shall I change it?')


def set_lut(text, luts, last_reply=''):
    state = {'panel_references': PANELS, 'selection': {'selected_panels': []}, '_last_reply': last_reply}
    PyFiguresAdapter('unused').validate_tool_call(
        'use_pyfigures_tool', {'tool_name': 'set_lut', 'arguments': {'panel_ref': 'A', 'luts': luts}}, state, text)


@pytest.mark.parametrize('text', ['fix it', 'yes', 'ok do it', 'go ahead', 'oui', 'the first option', '1'])
def test_colours_the_assistant_offered_and_the_user_accepted(text):
    set_lut(text, ['MAGENTA', 'GREEN'], OFFER)


def test_a_colour_blind_request_leaves_the_choice_to_the_assistant():
    set_lut('make a colour blind safe', ['MAGENTA', 'GREEN'])
    set_lut('is it colorblind friendly?\nfix it', ['CYAN', 'YELLOW'])


def test_everything_grayscale_may_put_gray_on_every_channel():
    set_lut('make everything grayscale', ['GRAY', 'GRAY'])
    set_lut('black and white please', ['GRAY', 'GRAY'])
    with pytest.raises(NeedsClarification, match='could no longer be told apart'):
        set_lut('try gray', ['GRAY', 'GRAY'])


NINE = {'selection': {'selected_panels': []},
        'panel_references': [{'panel_id': f'{i // 3}/{i % 3}', 'letters': [letter]} for i, letter in enumerate('ABCDEFGHI')]}


def call(text, tool, arguments, state=NINE):
    PyFiguresAdapter('unused').validate_tool_call('use_pyfigures_tool', {'tool_name': tool, 'arguments': arguments}, state, text)


def test_several_requests_in_one_sentence_each_name_their_panel():
    """'add bars to a d e, remove the letter of b, and make h green': removing B's letter
    was refused because "make h" was taken for the only panel named."""
    text = 'add bars to a d e, remove the letter of b, and make h green'
    call(text, 'edit_panel_letters', {'action': 'remove', 'scope': 'panels', 'panel_ids': ['0/1'], 'removal_request': text})
    call(text, 'set_scale_bar', {'panel_ref': '1/0', 'bar_width_in_units': 20})
    with pytest.raises(ValueError, match='PANEL_ADDRESS_MISMATCH'):
        call('make h bigger', 'edit_panel_letters', {'action': 'style', 'scope': 'panels', 'panel_ids': ['0/1'], 'font_size': 20})


@pytest.mark.parametrize('text', ['make it fit one column of nature', 'single column for cell please',
                                  'format it for science, double column'])
def test_a_column_of_a_journal_is_a_width_not_a_layout(text):
    with pytest.raises(ValueError, match='JOURNAL_COLUMN'):
        call(text, 'arrange_live_images', {'columns': 1})
    call(text, 'resize_figure', {'journal': 'nature', 'column': 'single'})


@pytest.mark.parametrize('text', ['put everything in one column', 'arrange the panels in one column for nature',
                                  'stack them in a single column, it is for cell'])
def test_a_column_layout_is_still_a_layout(text):
    call(text, 'arrange_live_images', {'columns': 1})


@pytest.mark.parametrize('text', ['make it publication ready', 'is it ready for submission? make it submission-ready'])
def test_publication_ready_checks_and_asks_before_changing(text):
    for tool, arguments in (('resize_figure', {'width_mm': 89}), ('edit_panel_letters', {'action': 'style', 'scope': 'all', 'color': '#ffffff'})):
        with pytest.raises(ValueError, match='VAGUE_REQUEST'):
            call(text, tool, arguments)
    call(text, 'review_submission_readiness', {'width_mm': 89})
    call(text, 'check_resolution', {'min_dpi': 300})


@pytest.mark.parametrize('text', ['make it publication ready\nyes, fix the width', 'make it publication ready for nature',
                                  'make it publication ready at 89 mm'])
def test_publication_ready_with_an_answer_or_a_target_goes_ahead(text):
    call(text, 'resize_figure', {'width_mm': 89})


@pytest.mark.parametrize('text', ['make the letter of #3 red', 'the letter on number 3 is too small'])
def test_a_panel_number_shown_on_the_canvas_names_the_panel(text):
    call(text, 'edit_panel_letters', {'action': 'style', 'scope': 'panels', 'panel_ids': ['#3'], 'color': '#ff0000'})


@pytest.mark.parametrize('text', ['the colors look unnatural can this be fixed', 'restore the original colours',
                                  'back to the default colors', 'the colours are weird', 'normal colours please'])
def test_colours_back_to_normal_restore_the_image_own_luts(text):
    """'the colors look unnatural can this be fixed' (user chat 2026-11-12): the model chose
    RED, was refused, and the user was never offered the image's own colours."""
    set_lut(text, ['NONE', 'NONE'])
    set_lut(text, ['DEFAULT', None])
    with pytest.raises(ValueError, match='use "NONE" for each channel'):
        set_lut(text, ['BLUE', None])                         # an invented colour: told to use NONE


def test_the_clarification_offers_the_image_own_colours_and_yes_accepts_it():
    with pytest.raises(NeedsClarification, match="image's own colours") as asked:
        set_lut('make it look better', ['BLUE', None])
    set_lut('yes', ['NONE', 'NONE'], str(asked.value))
    set_lut('the default one', ['NONE', 'NONE'], str(asked.value))
    with pytest.raises(NeedsClarification):
        set_lut('yes', ['CYAN', None], str(asked.value))     # not what was offered


@pytest.mark.parametrize('text', ['give each image bg a different bg color', 'make the panel bg black',
                                  'image px size is 0.2 um'])
def test_an_abbreviation_after_image_is_not_a_panel_name(text):
    """'give each image bg a different bg color' (user chat 2026-11-12): refused with
    "There is no panel 'bg' in this figure"."""
    call(text, 'set_image_property', {'panel_ref': '0/0', 'property_name': 'fill_color', 'value': '16711680'})


def test_a_panel_that_does_not_exist_is_still_asked_about():
    with pytest.raises(NeedsClarification, match="There is no panel 'aa'"):
        call('select image aa, then make its letter blue', 'set_image_property',
             {'panel_ref': '0/0', 'property_name': 'fill_color', 'value': '0'})


RESTORED = ("Fixed — E now shows its natural colors. The weird orange-yellow tint was the RED_HOT "
            "LUT on channel 1, now removed.")


@pytest.mark.parametrize('text', ['restore it as it was', 'put it back', 'revert that', 'remets comme avant'])
def test_going_back_to_the_lut_the_last_reply_named(text):
    """'restore it as it was' (user chat 2026-11-12): RED_HOT, named in the reply that had
    just removed it, was refused as 'not named by the request'."""
    set_lut(text, ['RED_HOT', None], RESTORED)
    with pytest.raises(NeedsClarification):
        set_lut(text, ['CYAN', None], RESTORED)                # not what it was


def test_a_qualified_every_is_not_all_letters():
    """'rotate A, then make the letter bold on every rotated panel' (2026-11-12): checked
    as 'all 9 letters bold' and sent back as unfinished although only A is rotated."""
    adapter = PyFiguresAdapter('unused')
    asked = []
    adapter.request = lambda *a, **k: asked.append(a) or {'panels': [
        {'panel_id': '0/0', 'letters': [{'text': 'A', 'bold': True}]},
        {'panel_id': '0/1', 'letters': [{'text': 'B', 'bold': False}]}]}
    state = {'selection': {'selected_panels': []}}
    assert adapter._verify_letter_style_reply('make the letter bold on every rotated panel',
                                              'Done: the letter of A is bold.', state) is None
    assert not asked                                           # nothing was checked against all
    flagged = adapter._verify_letter_style_reply('make every letter bold', 'Done: all letters are bold.', state)
    assert flagged['evidence']['mismatched_panel_ids'] == ['0/1']    # a plain "every" still counts


@pytest.mark.parametrize('text', ['how many channels does this imahge have', 'how big is panel A',
                                  'how much space is there between panels'])
def test_how_many_asks_for_a_number_not_steps(text):
    """'how many channels does this imahge have' (user chat 2026-11-12) was answered with the
    channel-split guide."""
    adapter = PyFiguresAdapter('unused')
    adapter.request = lambda *a, **k: {'status': 'explained', 'steps': ['Click the image.'], 'title': 'Split channels'}
    assert adapter.finalize_manual_response(text) is None
    assert adapter.finalize_manual_response('how do I split the channels') is not None


def test_colours_nobody_named_are_still_refused():
    with pytest.raises(NeedsClarification, match='does not name the colour table'):
        set_lut('fix it', ['MAGENTA', 'GREEN'])                       # nothing was offered
    with pytest.raises(NeedsClarification, match='does not name the colour table'):
        set_lut('yes', ['ORANGE_HOT', 'GREEN'], OFFER)                # not what was offered
    with pytest.raises(NeedsClarification, match='does not name the colour table'):
        set_lut('make the letters bigger', ['MAGENTA', 'GREEN'], OFFER)   # no acceptance


@pytest.mark.parametrize('text', ['i wanna edit smallest >ROI inset in b', 'I want to adjust the ROI in b',
                                  'open the editor so I can move it myself', 'let me edit the arrow in c by hand'])
def test_i_want_to_edit_it_opens_the_editor_and_changes_nothing(text):
    """"i wanna edit smallest ROI inset in b" made a second inset (user chat 2026-11-12)."""
    with pytest.raises(ValueError, match='SELF_EDIT'):
        call(text, 'roi_to_inset', {'panel_ref': 'B', 'annotation_index': 6})
    call(text, 'open_annotation_editor', {'panel_ref': 'B'})          # what to do instead


FIVE = {'selection': {'selected_panels': []},
        'panel_references': [{'panel_id': f'0/{i}', 'letters': [l]} for i, l in enumerate('abcde')]}


def _fake(state, opened, fail=None):
    def request(operation, arguments=None):
        if operation == 'inspect':
            return state
        if operation == 'open_annotation_editor':
            if fail:
                raise RuntimeError(fail)
            opened.append(arguments)
            return {'status': 'scheduled'}
        raise AssertionError(operation)
    return request


def test_have_me_edit_the_position_manually_opens_the_last_panel_editor():
    """'great now segment nuclei in d' ... 'not so bad, have me edit the position manually':
    the model searched and opened it 35 s later (user chat 2026-11-13)."""
    adapter, opened = PyFiguresAdapter('unused'), []
    adapter.request = _fake(FIVE, opened)
    assert adapter.preflight_manual_response('great now segment nuclei in d') is None
    out = adapter.preflight_manual_response('not so bad, have me edit the position manually')
    assert opened == [{'panel_ref': 'd', 'tab': 'annotations'}] and 'OK' in out['content']


def test_i_wanna_edit_the_roi_in_b_opens_its_editor_at_once():
    """Two questions came before the editor opened (user chat 2026-11-12)."""
    adapter, opened = PyFiguresAdapter('unused'), []
    adapter.request = _fake(FIVE, opened)
    out = adapter.preflight_manual_response('I wanna edit the ROI of the inset in b')
    assert opened == [{'panel_ref': 'b', 'tab': 'annotations'}] and 'OK' in out['content']
    # the next turn: "it" is that panel
    out = adapter.preflight_manual_response('i wanna edit it myself')
    assert opened[-1] == {'panel_ref': 'b', 'tab': 'annotations'} and len(opened) == 2
    # the crop of panel c opens on its crop tab
    adapter.preflight_manual_response('let me crop panel c myself')
    assert opened[-1] == {'panel_ref': 'c', 'tab': 'crop'}


@pytest.mark.parametrize('text', ['I wanna move the roi of one of the insets in b, open the dioalog for me',
                                  'open the editor of panel b', 'open panel b editor please'])
def test_open_the_dialog_for_me_opens_it(text):
    adapter, opened = PyFiguresAdapter('unused'), []
    adapter.request = _fake(FIVE, opened)
    out = adapter.preflight_manual_response(text)
    assert opened == [{'panel_ref': 'b', 'tab': 'annotations'}] and 'OK' in out['content']


@pytest.mark.parametrize('text', ['again i made a mistake', 'I said open it again', 'reopen it', 'oops I pressed cancel',
                                  'open the editor again please', 'again'])
def test_a_mistake_in_the_editor_reopens_it(text):
    """"again i made a mistake" after the editor of b opened was asked "what was the
    mistake?"; "I said open it again" then went through a tool search (user chat 2026-11-13)."""
    adapter, opened = PyFiguresAdapter('unused'), []
    adapter.request = _fake(FIVE, opened)
    adapter.preflight_manual_response("i don't like the position of one inset generating ROI in b open it for me so i can edit it")
    assert opened == [{'panel_ref': 'b', 'tab': 'annotations'}]
    out = adapter.preflight_manual_response(text)
    assert opened[-1] == {'panel_ref': 'b', 'tab': 'annotations'} and len(opened) == 2
    assert out['evidence']['reopened'] and 'again' in out['content']


def test_a_mistake_reopens_the_editor_the_model_opened():
    adapter, opened = PyFiguresAdapter('unused'), []
    adapter.request = _fake(FIVE, opened)
    adapter._turns_since_editor = 99
    call_args = {'tool_name': 'open_annotation_editor', 'arguments': {'panel_ref': 'c', 'tab': 'crop'}}
    adapter.validate_tool_call('use_pyfigures_tool', call_args, FIVE, 'open the crop of panel c')
    adapter.preflight_manual_response('oops, I made a mistake')
    assert opened == [{'panel_ref': 'c', 'tab': 'crop'}]


@pytest.mark.parametrize('text', ['I made a mistake, undo it', 'again i made a mistake, make the ROI red',
                                  'I made a mistake in my last message'])
def test_a_mistake_with_another_request_is_not_a_reopen(text):
    adapter, opened = PyFiguresAdapter('unused'), []
    adapter.request = _fake(FIVE, opened)
    adapter.preflight_manual_response('I wanna edit the ROI of the inset in b')
    assert adapter.preflight_manual_response(text) is None and len(opened) == 1


def test_a_late_mistake_is_not_a_reopen():
    adapter, opened = PyFiguresAdapter('unused'), []
    adapter.request = _fake(FIVE, opened)
    adapter.preflight_manual_response('I wanna edit the ROI of the inset in b')
    adapter._turns_since_editor = 5
    assert adapter.preflight_manual_response('I made a mistake') is None and len(opened) == 1


UNCROPPED = {'is_error': False, 'content': json.dumps({
    'result': 'Image 1 in group [1]: crop_left=0, crop_right=0, crop_top=0, crop_bottom=0.', 'document_changed': True})}
UNCROP_CALL = {'tool_name': 'transform_image',
               'arguments': {'crop_bottom': 0, 'crop_left': 0, 'crop_right': 0, 'crop_top': 0, 'panel_ref': 'e'}}


@pytest.mark.parametrize('text', ['uncrop it', 'please remove the crop of panel e', 'reset the crop', 'Uncrop e.'])
def test_uncrop_is_answered_from_the_readback(text):
    """The crop was removed in 1.4 s, then a figure read and a 34 s model answer (user chat
    2026-11-13): the readback already says every side is 0."""
    out = PyFiguresAdapter('unused').verified_completion('use_pyfigures_tool', UNCROP_CALL, UNCROPPED, FIVE, text)
    assert out and 'panel **e** is uncropped' in out


@pytest.mark.parametrize('text', ['uncrop it and make it bigger', 'crop e by 10 pixels', 'uncrop all panels except b'])
def test_other_crop_requests_still_get_the_model_answer(text):
    assert PyFiguresAdapter('unused').verified_completion('use_pyfigures_tool', UNCROP_CALL, UNCROPPED, FIVE, text) is None


def test_uncrop_not_verified_gets_the_model_answer():
    half = {'is_error': False, 'content': json.dumps({'result': 'crop_left=0, crop_right=0, crop_top=10, crop_bottom=0.',
                                                      'document_changed': True})}
    assert PyFiguresAdapter('unused').verified_completion('use_pyfigures_tool', UNCROP_CALL, half, FIVE, 'uncrop it') is None


CROP_320 = {'tool_name': 'transform_image',
            'arguments': {'crop_bottom': 320, 'crop_left': 0, 'crop_right': 0, 'crop_top': 0, 'panel_ref': '#5'}}


@pytest.mark.parametrize('text', ['crop #5 so that the burnt in scale bar gets hidden', 'crop g to the nuclei',
                                  'remove the black border of e'])
def test_a_crop_chosen_from_the_image_needs_the_panel_preview_first(text):
    """The model looked at the whole figure, then cut 320 px blind (user chat 2026-11-13)."""
    adapter = PyFiguresAdapter('unused')
    with pytest.raises(ValueError, match=r'CROP_NEEDS_PANEL_PREVIEW.*preview_panel\(panel_ref="#5"\)'):
        adapter.validate_tool_call('use_pyfigures_tool', CROP_320, FIVE, text)
    adapter.validate_tool_call('use_pyfigures_tool', {'tool_name': 'preview_panel', 'arguments': {'panel_ref': '#5'}}, FIVE, text)
    adapter.validate_tool_call('use_pyfigures_tool', CROP_320, FIVE, text)       # after the look: fine
    with pytest.raises(ValueError, match='CROP_NEEDS_PANEL_PREVIEW'):           # a new request needs a new look
        adapter.validate_tool_call('use_pyfigures_tool', CROP_320, FIVE, text + ' please')


@pytest.mark.parametrize('text,allowed', [('I would prefer triangular ROIs, can you do that?', True),
                                          ('remove all the boxes in e', True),
                                          ('great but I wanted squares instead of circles', True),
                                          ('make the ROIs of e thicker', False),
                                          ('how many cells are in e', False)])
def test_bulk_roi_removal_needs_words_that_ask_for_it(text, allowed):
    """'I would prefer triangular ROIs': 26 remove_annotation calls (2026-11-13);
    remove_rois does it at once, but only when removing or replacing was asked."""
    removal = {'tool_name': 'remove_rois', 'arguments': {'panel_ref': 'e'}}
    if allowed:
        call(text, 'remove_rois', {'panel_ref': 'e'})
    else:
        with pytest.raises(ValueError, match='REMOVAL_NOT_REQUESTED'):
            PyFiguresAdapter('unused').validate_tool_call('use_pyfigures_tool', removal, FIVE, text)


@pytest.mark.parametrize('text', ['move the smallest inset in b by 100 px to the right',
                                  'move the smallest inset in b by 100px to the right', 'shift the inset of b a bit left'])
def test_moving_an_inset_by_a_distance_is_answered_at_once(text):
    """Twice the model searched eight times for an inset offset and stopped
    (user chats 2026-11-13): an inset sits in a corner; say so and offer the rest."""
    adapter = PyFiguresAdapter('unused')
    adapter.request = _fake(FIVE, [])
    out = adapter.preflight_manual_response(text)
    assert out and 'cannot be moved by a distance' in out['content'] and 'panel **b**' in out['content']
    assert '- Move the ROI it shows instead' in out['content']
    assert ('top right' in out['content']) == ('right' in text)


@pytest.mark.parametrize('text', ['move the inset of b to the bottom left', 'move the inset to the other corner',
                                  'move the ROI of the inset in b 100 px to the right', 'make the inset in b bigger'])
def test_inset_requests_it_can_do_go_to_the_model(text):
    adapter = PyFiguresAdapter('unused')
    adapter.request = _fake(FIVE, [])
    assert adapter.preflight_manual_response(text) is None


def test_rois_on_cells_need_a_look_at_the_panel():
    """'can you draw ROIs over every cell in e': two boxes placed by eye from the whole
    figure, both off target (user chat 2026-11-13)."""
    adapter, text = PyFiguresAdapter('unused'), 'cna you draw ROIs over every cell in e'
    box = {'tool_name': 'add_roi_rect', 'arguments': {'panel_ref': 'e', 'x': 35, 'y': 98, 'width': 64, 'height': 64}}
    with pytest.raises(ValueError, match=r'LOOK_AT_THE_PANEL_FIRST.*detect_objects\(panel_ref="e"\)'):
        adapter.validate_tool_call('use_pyfigures_tool', box, FIVE, text)
    adapter.validate_tool_call('use_pyfigures_tool', {'tool_name': 'detect_objects', 'arguments': {'panel_ref': 'e'}}, FIVE, text)
    adapter.validate_tool_call('use_pyfigures_tool', {'tool_name': 'preview_panel', 'arguments': {'panel_ref': 'e'}}, FIVE, text)
    adapter.validate_tool_call('use_pyfigures_tool', box, FIVE, text)            # after the look: fine
    adapter.validate_tool_call('use_pyfigures_tool', box, FIVE, 'add a red box at 35, 98, 64 x 64 in e')


@pytest.mark.parametrize('text', ['crop 320 px from the bottom of #5', 'uncrop it', 'crop e by 10 on each side',
                                  'give e the same crop as d'])
def test_a_crop_with_its_numbers_needs_no_preview(text):
    call = UNCROP_CALL if text == 'uncrop it' else CROP_320
    PyFiguresAdapter('unused').validate_tool_call('use_pyfigures_tool', call, FIVE, text)


@pytest.mark.parametrize('text', ['open the export dialog', "don't open the editor, move the ROI in b up"])
def test_other_dialogs_or_no_dialog_go_to_the_model(text):
    adapter = PyFiguresAdapter('unused')
    adapter.request = _fake(FIVE, [])
    assert adapter.preflight_manual_response(text) is None


def _letters(b_style):
    base = dict(font_family='Segoe UI', font_size=9.0, bold=False, italic=False, underline=False, background=None)
    return {'panels': [{'panel_id': f'0/{i}', 'letters': [dict(base, text=t, color=0xFFFFFF if i % 2 else 0,
                                                               **(b_style if t == 'b' else {}))]}
                       for i, t in enumerate('abcde')]}


def test_consistent_letters_are_checked_and_the_choices_offered():
    """b stayed the only bold letter with a white box; the reply said they were consistent
    (user chat 2026-11-12)."""
    adapter = PyFiguresAdapter('unused')
    adapter.request = lambda op, args=None: _letters({'bold': True, 'background': '#ffffff'})
    out = adapter._verify_response("don't change font size and use consitent fonts for all letters...", 'Done.', {})
    assert out['evidence']['differing'] == {'bold': ['b'], 'background box': ['b']}
    assert 'Make b like the other letters' in out['content'] and 'Make every letter like b' in out['content']
    adapter.request = lambda op, args=None: _letters({})          # only the colours differ: fine
    assert adapter._verify_response('use consistent fonts for all letters', 'Done.', {}) is None


def test_an_unclear_panel_is_asked_with_the_editor_among_the_choices():
    adapter, opened = PyFiguresAdapter('unused'), []
    adapter.request = _fake(FIVE, opened)
    out = adapter.preflight_manual_response('I want to edit the ROI myself')
    assert not opened and 'Open the editor of panel **b**' in out['content'] and 'tell me the change' in out['content']


def test_an_editor_already_open_is_said_so():
    adapter, opened = PyFiguresAdapter('unused'), []
    adapter.request = _fake(FIVE, opened, fail='ANNOTATION_EDITOR_OPEN: the native editor is open')
    out = adapter.preflight_manual_response('I wanna edit the arrow in d')
    assert 'already open' in out['content']


@pytest.mark.parametrize('text', ['make the ROI in b red', 'I want to edit the title of b to say Control',
                                  'I want to change the letters myself', 'move the inset in b up'])
def test_edits_with_a_value_or_not_of_one_panel_go_to_the_model(text):
    adapter = PyFiguresAdapter('unused')
    adapter.request = _fake(FIVE, [])
    out = adapter.preflight_manual_response(text)
    assert out is None


@pytest.mark.parametrize('text', ['I want to edit the title to say Control', 'I want to edit b: make the ROI red',
                                  'make it bigger so I can see it', 'I want to adjust the inset size by 20%'])
def test_an_edit_with_its_value_is_still_made(text):
    call(text, 'roi_to_inset', {'panel_ref': 'B', 'annotation_index': 6})
