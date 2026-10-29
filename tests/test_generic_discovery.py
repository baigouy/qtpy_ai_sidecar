from types import SimpleNamespace
from qtpy_ai_sidecar.mcp_client import MCPHub


def hub(count=20):
    h = MCPHub({})
    for i in range(count):
        tool = SimpleNamespace(name=f'app_tool_{i:02d}', description=f'Digest number {i}. Long details follow here.',
                               inputSchema={'type': 'object', 'properties': {'x': {'type': 'integer'}}})
        h.tools[f't{i:02d}'] = ('app', None, tool)
    return h


def test_search_gives_whole_schemas_for_the_best_two_only():
    found = hub().find('digest')
    assert found['total'] == 20 and len(found['tools']) == 6
    assert ['arguments_schema' in t for t in found['tools']] == [True, True, False, False, False, False]
    short = found['tools'][2]
    assert short['summary'] == 'Digest number 2.' and short['name'] in short['schema']


def test_exact_name_search_returns_that_schema_first():
    found = hub().find('app_tool_17')
    assert found['tools'][0]['name'] == 'app_tool_17' and 'arguments_schema' in found['tools'][0]


def test_summary_only_hit_is_not_callable_until_its_schema_was_found(tmp_path):
    import asyncio
    import json
    from qtpy_ai_sidecar.config import Config
    from qtpy_ai_sidecar.engine import Engine

    class Hub(MCPHub):
        def __init__(self, servers):
            super().__init__(servers)
            self.tools = hub().tools
            self.calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, ident, arguments, emit):
            self.calls.append(ident)
            return {'is_error': False, 'content': '{"done": true}', 'structured': None}

    def call(name, arguments):
        return {'role': 'assistant', 'content': '', 'tool_calls': [{'id': name + str(len(seen)), 'type': 'function',
                'function': {'name': name, 'arguments': json.dumps(arguments)}}]}, {}

    seen = []

    class Model:
        async def complete(self, messages, tools, cancel, emit, max_tokens=None, final_only=False):
            seen.append([m for m in messages if m['role'] == 'tool'])
            step = len(seen)
            if step == 1:
                return call('find_application_tools', {'query': 'digest'})
            if step == 2:     # the 4th hit came as a summary only
                return call('execute_application_tool', {'tool_id': 't03', 'arguments': {'x': 1}})
            if step == 3:
                return call('find_application_tools', {'query': 'app_tool_03'})
            if step == 4:
                return call('execute_application_tool', {'tool_id': 't03', 'arguments': {'x': 1}})
            return {'role': 'assistant', 'content': 'Done.'}, {}

    hubs = []
    engine = Engine(Config(state_dir=str(tmp_path)), backend=Model(),
                    hub_factory=lambda servers: hubs.append(Hub(servers)) or hubs[-1])
    asyncio.run(engine.turn('digest it', lambda *args: None))
    refused = seen[2][-1]['content']
    assert 'not been described' in refused and 'app_tool_03' in refused and 'integer' in refused    # the schema comes back
    assert hubs[0].calls == ['t03']      # executed once, after its schema was found


def test_refused_undescribed_tool_can_be_repeated_without_another_search(tmp_path):
    import asyncio
    import json
    from qtpy_ai_sidecar.config import Config
    from qtpy_ai_sidecar.engine import Engine

    class Hub(MCPHub):
        def __init__(self, servers):
            super().__init__(servers)
            self.tools = hub().tools
            self.calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, ident, arguments, emit):
            self.calls.append(ident)
            return {'is_error': False, 'content': '{"done": true}', 'structured': None}

    steps = []

    class Model:
        async def complete(self, messages, tools, cancel, emit, max_tokens=None, final_only=False):
            steps.append(1)
            if len(steps) <= 2:
                return {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'c%d' % len(steps), 'type': 'function',
                        'function': {'name': 'execute_application_tool',
                                     'arguments': json.dumps({'tool_id': 't05', 'arguments': {'x': 1}})}}]}, {}
            return {'role': 'assistant', 'content': 'Done.'}, {}

    hubs = []
    engine = Engine(Config(state_dir=str(tmp_path)), backend=Model(),
                    hub_factory=lambda servers: hubs.append(Hub(servers)) or hubs[-1])
    asyncio.run(engine.turn('go', lambda *args: None))
    assert hubs[0].calls == ['t05']


def test_action_enum_phrases_are_searchable():
    h = hub()
    gui = SimpleNamespace(name='app_gui', description='Control a window.', inputSchema={
        'type': 'object', 'properties': {'params': {'type': 'object', 'properties': {
            'action': {'type': 'string', 'enum': ['add_feature', 'edit_sequence']}}}}})
    h.tools['gui'] = ('app', None, gui)
    h.tools['db'] = ('app', None, SimpleNamespace(
        name='app_feature_db_add', description='Add a feature to the feature database.',
        inputSchema={'type': 'object', 'properties': {}}))
    found = h.find('add feature to the plasmid')
    assert [t['name'] for t in found['tools'][:2]] == ['app_gui', 'app_feature_db_add']
    assert h.find('edit_sequence')['tools'][0]['name'] == 'app_gui'
    assert h.find('digest')['total'] == 20      # a query without enum vocabulary is unchanged


def test_text_only_recovery_survives_an_invalid_final_reply():
    import asyncio
    from qtpy_ai_sidecar.config import Config
    from qtpy_ai_sidecar.engine import Engine
    from qtpy_ai_sidecar.qwen_protocol import ReplyProtocolError

    class Model:
        async def complete(self, *args, **kwargs):
            raise ReplyProtocolError('Unknown function in model reply; no tool submitted: find_application_tools')

    events = []
    engine = Engine(Config(state_dir='.'), backend=Model(), hub_factory=lambda servers: hub())
    summary = asyncio.run(engine._stopped_text_summary([], lambda *args: events.append(args)))
    assert summary['role'] == 'assistant' and 'could not complete' in summary['content']
    assert not summary.get('tool_calls')


def test_flat_arguments_are_nested_under_a_lone_params_object():
    schema = {'$defs': {'In': {'properties': {'path': {}, 'start': {}}}},
              'properties': {'params': {'$ref': '#/$defs/In'}}, 'required': ['params']}
    tool = SimpleNamespace(inputSchema=schema)
    wrap = MCPHub._wrapped
    assert wrap(tool, {'path': 'live', 'start': 1}) == {'params': {'path': 'live', 'start': 1}}
    assert wrap(tool, {'params': {'path': 'x'}}) == {'params': {'path': 'x'}}
    assert wrap(tool, {'path': 'live', 'bogus': 1}) == {'path': 'live', 'bogus': 1}
    assert wrap(tool, {}) == {}
    other = SimpleNamespace(inputSchema={'properties': {'a': {}}, 'required': ['a']})
    assert wrap(other, {'a': 1}) == {'a': 1}


def test_later_pages_are_compact_too():
    page = hub().find('digest', offset=6)
    assert [('arguments_schema' in t) for t in page['tools']][:3] == [True, True, False]
