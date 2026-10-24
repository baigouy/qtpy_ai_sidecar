import json
from qtpy_ai_sidecar.adapters.pyfigures import PyFiguresAdapter

def test_swap_completion_verified_and_numbered():
    host = PyFiguresAdapter('unused')
    result = dict(is_error=False, content=json.dumps(dict(operation_result=dict(action='swap_rows', completion_verified=True, first_row=1, second_row=2))))
    args = dict(tool_name='swap_rows')
    assert host.verified_completion('use_pyfigures_tool', args, result, {}, 'swap row 2 and row 1').startswith('Rows 2 and 1 swapped.')
    assert host.verified_completion('use_pyfigures_tool', args, result, {}, 'swap row 2 and row 1 and remove letters') is None
    assert host.verified_completion('use_pyfigures_tool', args, result, {}, 'swap row 3 and row 1') is None
    result['is_error'] = True
    assert host.verified_completion('use_pyfigures_tool', args, result, {}, 'swap row 2 and row 1') is None
