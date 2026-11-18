"""Is a message pasted from the assistant's last answer?

A user picking an offered option often copies it ("Rebuild it as a seaborn violin panel ...
(I could re-add them manually)"). Its "I" and "manually" are the assistant's words: read as
the user's, they turned the choice into "which panel do you want to edit yourself?"
(user chat 2026-11-18)."""
import re

_SHINGLE = 5            # words per window
_MIN_WORDS = 8          # shorter messages are the user's own ("yes", "do option 2")
_SHARE = 0.6            # this share of the message's windows found in the answer


def _words(text):
    text = re.sub(r'[*_`>#]+', ' ', str(text or ''))          # markdown of the answer
    return re.findall(r"[\w'’]+", text.casefold())


def quotes_reply(text, reply):
    """True when most of *text* is copied from *reply* (an answer of the assistant)."""
    words = _words(text)
    if len(words) < _MIN_WORDS or not reply:
        return False
    answer = _words(reply)
    if len(answer) < _SHINGLE:
        return False
    known = {tuple(answer[i:i + _SHINGLE]) for i in range(len(answer) - _SHINGLE + 1)}
    windows = [tuple(words[i:i + _SHINGLE]) for i in range(len(words) - _SHINGLE + 1)]
    return sum(w in known for w in windows) >= _SHARE * len(windows)
