"""The user's responsibility, accepted once before the first message.

User, 2026-11-17: "the user is responsible of what he says and will be sending
even if he is not doing it directly". Asked once for a model on this computer,
and once more the first time an online provider is used (data then leaves the
computer). Remembered per application in accepted_terms.json.
"""
import json

FILE = 'accepted_terms.json'

LOCAL = ('<p><b>Before your first message</b></p>'
         '<p>You are responsible for what you ask the model to do and for everything the chat does on your '
         'behalf, including what it reads, sends and changes for you without you typing it yourself '
         '(tool results, descriptions and previews of your work).</p>'
         '<p>Language models make mistakes: check every change before you use the result. Undo removes '
         'the chat\'s changes.</p>'
         '<p>This software is provided "as is", without warranty; its authors accept no liability for its use '
         'or for the models\' output.</p>')
ONLINE = ('<p><b>Online provider ({provider}, {host})</b></p>'
          '<p>Your messages, and everything the chat sends on your behalf (what it reads in the application, '
          'descriptions of your work and, depending on Model vision, images of it), leave this computer and go '
          'to that provider.</p>'
          '<p><b>You alone are responsible</b> for what is sent, even when the chat sends it for you: '
          'make sure it may be shared (unpublished data, personal or confidential information) and that this '
          'use respects the provider\'s terms and your institution\'s rules.</p>'
          '<p>Language models make mistakes: check every change before you use the result.</p>'
          '<p>This software is provided "as is", without warranty; its authors accept no liability for its use, '
          'for what is sent to the provider or for the models\' output.</p>')


def ask_user(parent, title, html):
    """True when the user accepts (a test replaces this)."""
    from qtpy.QtCore import Qt
    from qtpy.QtWidgets import QMessageBox
    box = QMessageBox(QMessageBox.Icon.Information, title, html, parent=parent)
    box.setTextFormat(Qt.TextFormat.RichText)
    accept = box.addButton('I understand and accept', QMessageBox.ButtonRole.AcceptRole)
    box.addButton('Cancel', QMessageBox.ButtonRole.RejectRole)
    box.exec()
    return box.clickedButton() is accept


def _load(config):
    try:
        return set(json.loads((config.storage() / FILE).read_text(encoding='utf-8')))
    except (OSError, ValueError, TypeError):
        return set()


def accepted(config, parent=None):
    """True once the user accepted the terms for this kind of model (local or
    online); asks when they have not yet."""
    host = config.online_host()
    kind = 'online' if host else 'local'
    done = _load(config)
    if kind in done:
        return True
    html = ONLINE.format(provider=config.provider, host=host) if host else LOCAL
    if not ask_user(parent, 'Your responsibility', html):
        return False
    done.add(kind)
    if kind == 'online':
        done.add('local')                  # the online text covers it
    try:
        path = config.storage() / FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sorted(done)), encoding='utf-8')
    except OSError:
        pass
    return True
