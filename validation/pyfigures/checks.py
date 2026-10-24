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
    replies=' '.join(str(v) for k,v in events if k=='assistant').lower()
    import re
    def normalized(value): return re.sub(r'\s*,\s*',',',value.lower())
    for alternatives in expect.get('reply_terms_any',[]):
        check(any(normalized(term) in normalized(replies) for term in alternatives),'Missing manual explanation: '+str(alternatives))
    if expect.get('reply_terms_any'):
        check(chr(96)*3 not in replies,'Unrequested code in manual help')
    for phrase in expect.get('reply_forbidden',[]):
        check(phrase.lower() not in replies,'Unsupported manual claim: '+phrase)
    if 'row_sizes' in expect:
        check([len(row) for row in after['rows']]==expect['row_sizes'],'Wrong row sizes')
    if 'keep_first' in expect:
        check([p['filename'] for p in after['letters']['panels']]==[p['filename'] for p in before['letters']['panels']][:expect['keep_first']],'Wrong panels retained')
    def styles_equal(actual,key,wanted):
        if key=='color_family' and wanted=='blue':
            try:
                r,g,b=[int(actual[i:i+2],16) for i in (1,3,5)]
                return b>=128 and b>r+32 and b>g and r<128
            except (TypeError,ValueError): return False
        if key=='placement':
            return set(str(actual).replace('_',' ').split())==set(str(wanted).replace('_',' ').split())
        return actual==wanted
    for p in after['letters']['panels']:
        for a in p['letters']:
            for key,wanted in expect.get('all_style',{}).items():
                check(styles_equal(a.get(key),key,wanted),'Wrong '+key+' on '+a['text']+': '+str(a.get(key)))
            specific=expect.get('panel_style',{})
            if a['text']==specific.get('ref'):
                for key,wanted in specific.items():
                    if key!='ref': check(styles_equal(a.get('color' if key=='color_family' else key),key,wanted),'Wrong selected '+key)
    if 'preserve_other_letters' in expect:
        ref=expect['preserve_other_letters']
        check([p['letters'] for p in before['letters']['panels'] if not any(a['text']==ref for a in p['letters'])]==[p['letters'] for p in after['letters']['panels'] if not any(a['text']==ref for a in p['letters'])],'Unselected letters changed')
    if 'preserve_selected_except' in expect:
        ref=expect.get('panel_style',{}).get('ref')
        ignored=set(expect['preserve_selected_except'])
        def selected_styles(snapshot):
            return [{k:v for k,v in a.items() if k not in ignored}
                    for p in snapshot['letters']['panels'] for a in p['letters'] if a['text']==ref]
        check(selected_styles(before)==selected_styles(after),'Unrequested selected letter property changed')
    edits=[]
    for kind,value in events:
        if kind=='tool_call':
            args=value.get('arguments',{})
            name=args.get('tool_name','') if 'use_pyfigures_tool' in value.get('name','') else value.get('name','')
            if name and not any(word in name for word in ('inspect','find_','get_','list_','preview','select_live','open_annotation','explain_','show_me_how','guidance')):
                edits.append(name)
    check(all(name in allowed for name in edits),'Unexpected mutation operation: '+str(edits))
    check(len(edits)<=1,'Efficiency: Too many mutation calls: '+str(edits))
    return failures
