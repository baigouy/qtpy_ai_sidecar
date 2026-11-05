"""User finding 2026-11-05: GUI how-to answers told what to click but never
offered to highlight the path or to open it. The adapter now adds the offer
itself, and the two options become answer buttons."""
from qtpy_ai_sidecar.adapters.pyfigures import PyFiguresAdapter
from qtpy_ai_sidecar.widgets import choices

# the two answers of the 2026-11-05 chat that should have offered it
CHANNELS = """Here's how to do it yourself in the PyFigures GUI:

1. **Click panel e** (the max-projection image in the middle row) to select it.
2. **Double-click the panel** - its Edit Image dialog opens.
3. Go to the **File Infos + Scale** tab - that's where the **channel order** is set.
4. Set the channel order to **3, 1, 2**.
5. Click **OK** to apply."""

CROP = """Sure! Here's how to fine-tune the crop on panel **e** yourself:

1. **Click panel e** to select it.
2. **Double-click it** (or right-click -> **Edit Image**) to open the image editor.
3. Go to the **Rotate + Crop** tab.
4. Enter the pixels to remove from each side.
5. Click **OK** to apply."""


def test_how_to_steps_end_with_the_two_offers_as_buttons():
    adapter = PyFiguresAdapter('unused')
    adapter.begin = lambda *a, **k: None
    for request, reply in (('the channels have not changed have me change them myself', CHANNELS),
                           ('cool I would like to fine tune it myself', CROP)):
        adapter._guided = False
        result = adapter.finalize_response(request, reply, {})
        assert result['content'].startswith(reply)
        assert result['content'].endswith(PyFiguresAdapter.GUI_HELP_OFFER)
        assert result['evidence']['gui_help_offered']
        # the buttons are the two offers, not the five steps
        assert choices(result['content']) == ['highlight where to click', 'open it for me']


def test_a_list_of_choices_gets_show_me_where_as_one_more_choice():
    adapter = PyFiguresAdapter('unused')
    reply = ("Which way do you want to change the colours of e?\n"
             "1. Right-click e -> Appearance -> Set LUT(s)\n"
             "2. Double-click e, File Infos + Scale tab, pick a LUT per channel")
    result = adapter.finalize_response('help me change channel color in e', reply, {})
    assert choices(result['content'])[-1] == '**Show me where to click**'
    assert len(choices(result['content'])) == 3


def test_no_offer_when_already_offered_guided_or_not_about_the_gui():
    adapter = PyFiguresAdapter('unused')
    offered = CROP + '\n\nWant me to show me where to click?'
    assert adapter.finalize_response('fine tune it myself', offered, {}) is None
    done = 'Done - panel **e** is cropped. All other panels are unchanged.'
    assert adapter.finalize_response('crop e', done, {}) is None
    # the chat already opened the editor / highlighted this turn
    adapter.validate_tool_call('use_pyfigures_tool', {'tool_name': 'open_annotation_editor',
                                                      'arguments': {'panel_ref': 'e', 'tab': 'crop'}}, {}, 'open the dialog for me')
    assert adapter.finalize_response('open the dialog for me', CROP, {}) is None


def test_steps_with_an_unrelated_question_keep_steps_out_of_the_buttons():
    text = CROP + '\n\nShould I **highlight where to click**, or **open it for me**?'
    assert choices(text) == ['highlight where to click', 'open it for me']
    # a plain options list is unchanged
    assert choices('Which one?\n1. Red\n2. Green') == ['Red', 'Green']
