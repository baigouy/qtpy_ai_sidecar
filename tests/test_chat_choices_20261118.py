"""Choices the user makes from the assistant's own offers (user chats, 2026-11-18).

- pasting an offered option ("Rebuild it as a seaborn violin panel ... (I could re-add them
  manually)") opened "which panel do you want to edit yourself?": the "I" was the assistant's;
- "I'll go for the box plot finally", answering "tell me which one you want and I'll keep only
  that plot and remove the other three", was refused as a removal nobody asked for;
- "just say the word and I'll switch it" was taken for an undone step, and a second
  "Nothing was changed" message followed every such offer.
"""
import pytest

from qtpy_ai_sidecar.engine import promises_action
from qtpy_ai_sidecar.quoting import quotes_reply

OFFER = ("1. **Leave it** - truncating is common.\n"
         "2. **Rebuild it as a seaborn violin panel** with `cut=0`... actually with the KDE extended past the "
         "data (`options={\"cut\": 2}`-style), so the violins taper smoothly - but that panel type has **no "
         "automatic significance brackets**, so we'd lose the **** annotations (I could re-add them manually).\n"
         "3. **Switch to a box plot**.\n\nWhich would you like?")


def test_a_pasted_option_is_recognised_as_the_assistants_words():
    pasted = ("Rebuild it as a seaborn violin panel with cut=0... actually with the KDE extended past the data "
              "(options={\"cut\": 2}-style), so the violins taper smoothly - but that panel type has no automatic "
              "significance brackets, so we'd lose the **** annotations (I could re-add them manually).")
    assert quotes_reply(pasted, OFFER)
    assert not quotes_reply("I want to edit the ROI in b manually please", OFFER)
    assert not quotes_reply("2", OFFER) and not quotes_reply("yes do the second one", OFFER)
    assert not quotes_reply(pasted, "")


def test_a_pasted_option_reads_as_a_self_edit_on_its_words_alone():
    """Why the paste check is needed: the words alone ask for a self-edit."""
    from qtpy_ai_sidecar.adapters.pyfigures import PyFiguresAdapter
    pasted = "Rebuild it as a seaborn violin panel, so we'd lose the **** annotations (I could re-add them manually)."
    assert PyFiguresAdapter._wants_to_edit_himself(pasted)


@pytest.mark.parametrize("reply, promised", [
    ("Just say the word - e.g. \"make it a box plot\" - and I'll switch it.", False),
    ("Tell me which one you want (a, b, c or d) and I'll keep only that plot and remove the other three.", False),
    ("If you want SD instead, I'll change it.", False),
    ("I'll now add the other four plot kinds as temporary panels.", True),
    ("Let me check the panel first.", True),
    ("Which one would you like?", False),
])
def test_an_offer_is_not_a_promised_step(reply, promised):
    assert promises_action(reply) is promised


def test_picking_from_an_offered_removal_is_a_removal_request():
    from qtpy_ai_sidecar.adapters.pyfigures import PyFiguresAdapter
    state = {"_last_reply": "Tell me which one you want (a, b, c or d) and I'll keep only that plot and "
                            "remove the other three."}
    accepts = PyFiguresAdapter._accepts_offered_removal
    assert accepts("I'll go for the box plot finally", state)
    assert accepts("c", state)
    assert not accepts("no, keep them all", state)
    assert not accepts("I'll go for the box plot", {"_last_reply": "Here is the box plot."})
    # a removal mentioned without being offered as a choice does not count
    assert not accepts("ok", {"_last_reply": "I removed the empty panel."})
