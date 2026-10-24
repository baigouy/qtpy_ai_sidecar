def test_qwen_final_channel_safety():
    import json
    from qtpy_ai_sidecar.qwen_protocol import parse_reply
    
    schemas = {'find_pyfigures_tools': {'properties': {'query': {'type': 'string'}, 'limit': {'type': 'integer'}}, 'required': []},
               'use_pyfigures_tool': {'properties': {'tool_name': {'type': 'string'}, 'arguments': {'type': 'object'}}, 'required': ['tool_name', 'arguments']}}
    tool = '<tool_call>\n<function=find_pyfigures_tools>\n<parameter=query>letter position center</parameter>\n<parameter=limit>6</parameter>\n</function>\n</tool_call>'
    result = parse_reply('Thinking about this. </think>\n' + tool, schemas, require_think_end=True)
    assert result['content'] == ''
    assert json.loads(result['tool_calls'][0]['function']['arguments']) == {'query': 'letter position center', 'limit': 6}
    assert parse_reply('Need to inspect. </think>Done.', schemas, True)['content'] == 'Done.'
    assert not parse_reply('<think>'+tool+'</think>Only an example.', schemas)['tool_calls']
    for invalid in (tool[:-12], tool.replace('find_pyfigures_tools', 'unknown'),
                    tool.replace('</function>', '<parameter=query>duplicate</parameter></function>'),
                    '```\n'+tool+'\n```', '<think>'+tool):
        try:
            parse_reply(invalid, schemas)
            raise AssertionError('Malformed/unsafe call accepted')
        except ValueError:
            pass
    nested = '<tool_call><function=use_pyfigures_tool><parameter=tool_name>edit_panel_letters</parameter><parameter=arguments>{"placement":"center","scope":"all"}</parameter></function></tool_call>'
    assert json.loads(parse_reply(nested, schemas)['tool_calls'][0]['function']['arguments'])['arguments']['placement'] == 'center'
    print('PASS: final-channel calls parsed; final text retained; thinking/examples/partial/unknown/duplicate calls rejected')
