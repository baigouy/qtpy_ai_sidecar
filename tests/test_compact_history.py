from qtpy_ai_sidecar.config import Config
from qtpy_ai_sidecar.engine import Engine

def engine(tmp_path, **kw):
    e=Engine(Config(state_dir=str(tmp_path),**kw),backend=object(),hub_factory=lambda *a:None)
    return e

def add(e, ident, size, discovery):
    e.messages.append({'role':'tool','tool_call_id':ident,'content':'x'*size})
    e._tool_meta[ident]=(e._turn,discovery)

def test_nothing_is_shortened_while_the_context_has_room(tmp_path):
    e=engine(tmp_path,context_tokens=65536)
    e._turn=1
    add(e,'old_edit',5000,False)
    e._turn=2
    assert e._outgoing()[-1]['content']=='x'*5000          # ~2k tokens of 64k: full results
    for i in range(30):add(e,f'find{i}',5000,True)          # ~52k tokens: past half the context
    assert len(e._outgoing()[1]['content'])<1000

def test_old_searches_and_earlier_turns_go_out_shortened_but_are_kept(tmp_path):
    e=engine(tmp_path,compact_from=0)
    e._turn=1
    add(e,'old_edit',5000,False)                 # an earlier turn's edit result
    e._turn=2
    for i in range(4):add(e,f'find{i}',5000,True)
    add(e,'edit',5000,False)                     # this turn's edit: never shortened
    sent={m.get('tool_call_id'):m['content'] for m in e._outgoing() if m.get('role')=='tool'}
    assert len(sent['old_edit'])<1000 and 'CURRENT_HOST_STATE' in sent['old_edit']
    assert len(sent['find0'])<1000 and len(sent['find1'])<1000
    assert len(sent['find2'])==len(sent['find3'])==5000      # the two latest searches stay whole
    assert len(sent['edit'])==5000
    assert all(len(m['content'])==5000 for m in e.messages if m.get('role')=='tool')   # history itself untouched

def test_compact_history_can_be_switched_off(tmp_path):
    e=engine(tmp_path,compact_history=False)
    e._turn=1
    add(e,'old',5000,False)
    e._turn=2
    assert e._outgoing()[-1]['content']=='x'*5000
