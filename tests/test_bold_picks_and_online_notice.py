"""Bold words in an answer can be clicked into the message box; the notice says
explicitly when the conversation and images leave the computer (online
providers only)."""
from qtpy.QtCore import QUrl
from qtpy.QtWidgets import QApplication

from qtpy_ai_sidecar.config import Config
from qtpy_ai_sidecar.widgets import AssistantDock, PICK_SCHEME, bold_as_picks


def test_bold_becomes_a_pick_link_but_not_code_or_links():
    out = bold_as_picks('Choose **3-2-2-2** or **2 rows**, not `**code**` nor [**a link**](https://x.org).')
    assert f'[**3-2-2-2**]({PICK_SCHEME}:3-2-2-2)' in out
    assert f'({PICK_SCHEME}:2%20rows)' in out
    assert '`**code**`' in out and '[**a link**](https://x.org)' in out
    assert bold_as_picks('no bold here') == 'no bold here'
    assert bold_as_picks('a ** b ** c') == 'a ** b ** c'          # not bold in Markdown either


def test_clicking_bold_text_puts_it_in_the_message_box(tmp_path):
    app = QApplication.instance() or QApplication([])
    dock = AssistantDock(Config(application='Demo', state_dir=str(tmp_path)))
    dock.show()
    layout = dock.add_message('assistant', 'Which split? **3-2-2-2** or **2-2-2-3**')
    browser = layout.itemAt(1).widget()
    anchors = []
    block = browser.document().begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            fmt = it.fragment().charFormat()
            if fmt.isAnchor():
                anchors.append((it.fragment().text(), fmt.anchorHref(), fmt.fontUnderline(), fmt.toolTip()))
            it += 1
        block = block.next()
    assert [a[0] for a in anchors] == ['3-2-2-2', '2-2-2-3']
    assert not any(a[2] for a in anchors) and all('message box' in a[3] for a in anchors)
    browser.anchorClicked.emit(QUrl(anchors[1][1]))
    assert dock.input.toPlainText() == '2-2-2-3'
    browser.anchorClicked.emit(QUrl('file:///C:/nowhere'))         # never navigates or crashes
    assert 'Which split?' in browser.toPlainText()
    user = dock.add_message('user', 'I said **this**').itemAt(1).widget()
    assert PICK_SCHEME not in user.toHtml()                        # only answers are clickable
    dock.shutdown()
    dock.close()


def test_online_provider_notice_only_when_data_leaves_the_computer(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    dock = AssistantDock(Config(application='Demo', state_dir=str(tmp_path)))
    assert dock.engine.config.online_host() is None
    assert 'outside this computer' not in dock.notice.text()
    assert dock.notice.text().startswith('⚠ Models can make mistakes')
    online = Config(application='Demo', state_dir=str(tmp_path), provider='mistral',
                    base_url='https://api.mistral.ai/v1', model='mistral-large-4',
                    notice='Check every panel.', remote_notice='Sent to {provider} at {host}: text and images.')
    assert online.online_host() == 'api.mistral.ai'
    dock.replace_engine(online)
    lines = dock.notice.text().splitlines()
    assert lines[0] == '⚠ Check every panel.'
    assert lines[1].startswith('⚠ Sent to ') and 'api.mistral.ai' in lines[1] and 'Mistral' in lines[1]
    default = Config(application='Demo', state_dir=str(tmp_path), provider='openrouter',
                     base_url='https://openrouter.ai/api/v1', model='openrouter/free')
    dock.replace_engine(default)
    assert 'outside this computer' in dock.notice.text() and 'openrouter.ai' in dock.notice.text()
    # a custom server on this computer is not online
    loop = Config(application='Demo', state_dir=str(tmp_path), provider='compatible',
                  base_url='http://127.0.0.1:8080/v1', model='m')
    assert loop.online_host() is None
    dock.replace_engine(loop)
    assert len(dock.notice.text().splitlines()) == 1
    dock.shutdown()
    dock.close()
