"""LitsearchAdapter against a stand-in for litsearch's GUI bridge (the same
authenticated loopback contract), without litsearch installed."""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from qtpy.QtWidgets import QApplication, QMainWindow, QWidget

from qtpy_ai_sidecar.adapters import litsearch as L
from qtpy_ai_sidecar.config import Config
from qtpy_ai_sidecar.engine import Engine

STATE = {'session_id': 's1', 'revision': 3, 'tab': 'Search', 'query': 'CyO balancer',
         'results': {'local': [{'label': 'L1', 'title': 'Balancers', 'page': 2}],
                     'external': [{'label': 'P1', 'source': 'pubmed', 'title': 'CyO'}]},
         'jobs': {}}


@pytest.fixture
def bridge(tmp_path):
    """Answers like litsearch's bridge: inspect -> state, other operations echoed."""
    seen = []
    state = dict(STATE)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            seen.append((self.headers['Authorization'], body))
            if self.headers['Authorization'] != 'Bearer t0ken':
                reply, code = {'error': 'unauthorized'}, 401
            elif body['operation'] == 'inspect':
                reply, code = {'result': state}, 200
            elif body['operation'] == 'show_paper':
                reply, code = {'error': 'No result L9: the results shown are L1-L1.'}, 200
            else:
                reply, code = {'result': {'echo': body['operation'], 'arguments': body['arguments']}}, 200
            data = json.dumps(reply).encode()
            self.send_response(code)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    descriptor = tmp_path / 'connection.json'
    descriptor.write_text(json.dumps({'url': f'http://127.0.0.1:{server.server_address[1]}/', 'token': 't0ken'}))
    yield descriptor, seen, state
    server.shutdown()
    server.server_close()


def test_requests_carry_the_token_and_return_results(bridge):
    descriptor, seen, _ = bridge
    adapter = L.LitsearchAdapter(descriptor)
    assert adapter.request('search_local', {'query': 'CyO'}) == {
        'echo': 'search_local', 'arguments': {'query': 'CyO'}}
    assert seen[-1][0] == 'Bearer t0ken' and seen[-1][1]['request_id']
    with pytest.raises(RuntimeError, match='No result L9'):
        adapter.request('show_paper', {'label': 'L9'})


def test_bridge_must_be_local(tmp_path):
    descriptor = tmp_path / 'c.json'
    descriptor.write_text(json.dumps({'url': 'http://example.org:80/', 'token': 'x'}))
    with pytest.raises(ValueError, match='must be local'):
        L.LitsearchAdapter(descriptor).request('inspect')


def test_context_and_cache_epoch_follow_the_gui(bridge):
    descriptor, _, state = bridge
    adapter = L.LitsearchAdapter(descriptor)
    assert adapter.context()['query'] == 'CyO balancer'
    before = adapter.read_cache_epoch()
    assert adapter.read_cache_epoch() == before
    state['revision'] += 1          # the user picked another result
    assert adapter.read_cache_epoch() != before
    state['jobs'] = {'index': {'status': 'done'}}
    assert adapter.read_cache_epoch() != before


def test_tools_are_classified_and_unknown_ones_left_to_their_server():
    adapter = L.LitsearchAdapter('unused.json')
    assert all(adapter.is_read_only_call(t, {}) is True for t in L.READ_ONLY_TOOLS)
    assert all(adapter.is_read_only_call(t, {'action': 'run', 'papers': ['P1']}) is False
               for t in L.VIEW_TOOLS | L.DATA_TOOLS)
    assert adapter.is_read_only_call('library', {}) is True
    assert adapter.is_read_only_call('library', {'action': 'list', 'query': 'wing'}) is True
    assert all(adapter.is_read_only_call('library', {'action': a}) is False
               for a in ('index', 'stop', 'remove', 'import'))
    assert adapter.is_read_only_call('library', {'action': 'duplicates'}) is True
    assert adapter.is_read_only_call('saved_reviews', {}) is True
    assert adapter.is_read_only_call('saved_reviews', {'action': 'open', 'name': 'x'}) is False
    assert adapter.is_read_only_call('screen_papers', {'review': 'r'}) is True
    assert adapter.is_read_only_call('screen_papers', {'review': 'r', 'papers': ['P1']}) is False
    assert adapter.is_read_only_call('some_other_server_tool', {}) is None
    assert len(L.TOOLS) == 22      # within the 24 passed to the model directly


def test_no_undo_is_offered():
    adapter = L.LitsearchAdapter('unused.json')
    assert adapter.finish() == {'controls': []} and not adapter.supports_preview
    with pytest.raises(ValueError, match='no undo'):
        adapter.control('undo')


def test_instructions_cover_labels_citations_jobs_and_keys():
    text = L.LitsearchAdapter('unused.json').context_instructions(STATE)
    for needed in ('L1, L2', 'P1, P2', 'get_evidence', 'not peer-reviewed', 'REPLACE',
                   'background jobs', 'Never ask for or write an API key', '1 local, 1 external'):
        assert needed in text


class Answer:
    """A model that answers from the host state without any tool."""
    def __init__(self):
        self.seen = None

    async def complete(self, messages, tools, cancel, emit, max_tokens=None):
        self.seen = messages
        return {'role': 'assistant', 'content': 'You found L1 (Balancers) and P1 (CyO).'}, {}


def test_engine_turn_gets_the_live_state_and_guidance(bridge, tmp_path):
    descriptor, seen, _ = bridge
    model = Answer()
    engine = Engine(Config(application='litsearch', state_dir=str(tmp_path / 'state')),
                    L.LitsearchAdapter(descriptor), backend=model)
    events = []
    asyncio.run(engine.turn('What did I find?', lambda *a: events.append(a)))
    host = next(m['content'] for m in model.seen if m['content'].startswith('[CURRENT_HOST_STATE]'))
    assert 'This is litsearch' in host and '"title": "Balancers"' in host
    assert any(e[0] == 'assistant' and 'L1' in e[1] for e in events)
    assert [b['operation'] for _, b in seen] == ['inspect']   # begin/finish need no bridge call


def test_config_from_dict_keeps_the_users_saved_connection(tmp_path):
    base = {'application': 'litsearch', 'provider': 'mistral', 'base_url': 'https://api.mistral.ai/v1',
            'model': 'mistral-large-4', 'state_dir': str(tmp_path), 'mcpServers': {'litsearch': {'command': 'x'}}}
    assert Config.from_dict(base).model == 'mistral-large-4'
    (tmp_path / 'connection.json').write_text(json.dumps({'provider': 'openrouter', 'model': 'openrouter/free',
                                                          'base_url': 'https://openrouter.ai/api/v1'}))
    config = Config.from_dict(base)
    assert (config.provider, config.model) == ('openrouter', 'openrouter/free')
    assert config.servers == {'litsearch': {'command': 'x'}} and base['mcpServers']   # input untouched


def test_attach_docks_beside_the_litsearch_window(tmp_path):
    app = QApplication.instance() or QApplication([])
    host = QMainWindow()
    host.setCentralWidget(QWidget())
    dock = L.attach_to_window(host, Config(application='litsearch', state_dir=str(tmp_path)), tmp_path / 'c.json')
    host.show()
    app.processEvents()
    assert dock.parent() is host and host.local_chat_dock is dock and not dock.isFloating()
    assert isinstance(dock.engine.adapter, L.LitsearchAdapter)
    assert dock.width() <= min(560, host.width() * .4) + 2
    dock.shutdown()
    host.close()
