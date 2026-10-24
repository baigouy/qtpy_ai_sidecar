"""Checks compare actual GUI state, never the model's claim."""
def verify(expect, before, after, events, allowed):
    failures=[]
    def check(ok, message):
        if not ok: failures.append(message)
    if 'letters' in expect:
        check(after['letters']['visible_letter_count']==expect['letters'],'Wrong visible letter count')
    if expect.get('letters')==24:
        check([p['letters'][0]['text'] if p['letters'] else None for p in after['letters']['panels']]==list('abcdefghijklmnopqrstuvwx'),'Wrong automatic letter sequence')
    if expect.get('preserve_letters'):
        check([p['letters'] for p in before['letters']['panels']]==[p['letters'] for p in after['letters']['panels']],'Unrequested lettering change')
    if expect.get('no_text'):
        check(not any(a.get('text','').casefold()==expect['no_text'].casefold() for a in after['annotations']),'Requested text remains')
    if expect.get('no_edit'):
        check(before['letters']==after['letters'] and before['annotations']==after['annotations'] and before['rows']==after['rows'],'UI handoff unexpectedly changed document')
    if 'selected' in expect:
        check(sorted(x for p in after['selection']['selected_panels'] for x in p['letters'])==sorted(expect['selected']),'Wrong live selection')
    if 'swap_rows' in expect:
        wanted=list(before['rows']); a,b=expect['swap_rows']; wanted[a-1],wanted[b-1]=wanted[b-1],wanted[a-1]
        check(after['rows']==wanted,'Wrong row membership/order')
        check([p['letters'][0]['text'] for p in after['letters']['panels']]==[p['letters'][0]['text'] for p in before['letters']['panels']],'Automatic letters did not follow positions')
    if 'swap_panels' in expect:
        ids=[next(i for i,p in enumerate(before['letters']['panels']) if p['letters'][0]['text']==ref) for ref in expect['swap_panels']]
        wanted=[p['filename'] for p in before['letters']['panels']]; a,b=ids; wanted[a],wanted[b]=wanted[b],wanted[a]
        check([p['filename'] for p in after['letters']['panels']]==wanted,'Wrong swapped panels')
    if 'insets' in expect:
        check(sum(a['type']=='Image2D' for a in after['annotations'])==expect['insets'],'Wrong inset count')
    if expect.get('roi_preserved'):
        check([a for a in before['annotations'] if a['type']=='Rectangle2D']==[a for a in after['annotations'] if a['type']=='Rectangle2D'],'Native conversion must retain ROI')
    if expect.get('annotation_handoff'):
        replies=' '.join(str(v) for k,v in events if k=='assistant').lower()
        check('editor' in replies or '?' in replies,'No clarification or editor handoff')
    edits=[]
    for kind,value in events:
        if kind=='tool_call':
            args=value.get('arguments',{})
            name=args.get('tool_name','') if 'use_pyfigures_tool' in value.get('name','') else value.get('name','')
            if name and not any(word in name for word in ('inspect','find_','get_','list_','preview','select_live','open_annotation')):
                edits.append(name)
    check(all(name in allowed for name in edits),'Unexpected mutation operation: '+str(edits))
    check(len(edits)<=1,'Too many mutation calls: '+str(edits))
    return failures
