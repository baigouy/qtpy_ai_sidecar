"""Checks compare actual GUI state, never the model's claim."""
def caption_markup_equal(actual,wanted):
    if actual==wanted:return True
    if not isinstance(actual,str) or not isinstance(wanted,str):return False
    from qtpy.QtGui import QTextDocument,QTextCursor
    documents=[]
    for markup in (actual,wanted):
        doc=QTextDocument();doc.setMarkdown(markup);documents.append(doc)
    if documents[0].toPlainText()!=documents[1].toPlainText():return False
    def styles(doc):
        result=[]
        for position in range(doc.characterCount()-1):
            cursor=QTextCursor(doc);cursor.setPosition(position);cursor.movePosition(QTextCursor.MoveOperation.NextCharacter,QTextCursor.MoveMode.KeepAnchor)
            fmt=cursor.charFormat();result.append((fmt.fontWeight(),fmt.fontItalic(),fmt.fontUnderline(),fmt.verticalAlignment()))
        return result
    return styles(documents[0])==styles(documents[1])

def verify(expect, before, after, events, allowed):
    failures=[]
    def check(ok, message):
        if not ok: failures.append(message)
    if 'letters' in expect:
        check(after['letters']['visible_letter_count']==expect['letters'],'Wrong visible letter count')
    if 'letter_sequence' in expect and expect['letter_sequence'] is not None:
        check([p['letters'][0]['text'] if p['letters'] else None for p in after['letters']['panels']]==expect['letter_sequence'],'Wrong requested letter sequence')
    elif expect.get('letters')==24 and 'letter_sequence' not in expect:
        check([p['letters'][0]['text'] if p['letters'] else None for p in after['letters']['panels']]==list('abcdefghijklmnopqrstuvwx'),'Wrong automatic letter sequence')
    if expect.get('preserve_letters'):
        check([p['letters'] for p in before['letters']['panels']]==[p['letters'] for p in after['letters']['panels']],'Unrequested lettering change')
    if expect.get('no_text'):
        check(not any(a.get('text','').casefold()==expect['no_text'].casefold() for a in after['annotations']),'Requested text remains')
    if expect.get('no_edit'):
        check(before['letters']==after['letters'] and before['annotations']==after['annotations'] and before['rows']==after['rows'],'UI handoff unexpectedly changed document')
        # A transaction can advance its revision with byte-identical XML.
        # Compare the persisted document and staged caption, not that counter.
        for field in ('document_digest','caption_digest'):
            if field in before and field in after:
                check(before[field]==after[field],'Saved '+field+' changed during a no-edit request')
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
    if expect.get('no_success_claim'):
        claimed=bool(re.search(r"^\s*(?:done\b|successfully\b)|\b(?:i have|i've|successfully)\s+(?:removed|deleted|moved|swapped|changed|rotated)\b",replies))
        check(not claimed,'Unsupported success claim for unresolved/no-op request')
    if expect.get('verify_row_deletion_report'):
        actual=len(before['rows'])-len(after['rows'])
        plain=re.sub(r'[*_`#]','',replies)
        claims=re.findall(r'\b(?:deleted|removed)\s+(?:all\s+)?(?:the\s+)?(\d+)\s+rows?\b',plain)
        claims+=re.findall(r'\b(\d+)\s+rows?\s+(?:were|have been)\s+(?:deleted|removed)\b',plain)
        check(all(int(n)==actual for n in claims),'Reported deleted-row count differs from actual state')
    # typographic apostrophes/quotes ("don’t", “aa”) count as their ASCII forms
    def normalized(value): return re.sub(r'\s*,\s*',',',value.lower().translate({0x2018:39,0x2019:39,0x201c:34,0x201d:34}))
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
        if key=='color_family':
            try:
                if isinstance(actual,int):actual=f'#{actual & 0xFFFFFF:06x}'
                r,g,b=[int(actual[i:i+2],16) for i in (1,3,5)]
                if wanted=='blue':return b>=128 and b>r+32 and b>g and r<128
                if wanted=='green':return g>=128 and g>r+32 and g>b+32
                if wanted=='red':return r>=128 and r>g+32 and r>b+32
            except (TypeError,ValueError):return False
            return False
        if key=='placement':
            return set(str(actual).replace('_',' ').split())==set(str(wanted).replace('_',' ').split())
        return actual==wanted
    for p in after['letters']['panels']:
        for a in p['letters']:
            for key,wanted in expect.get('all_style',{}).items():
                check(styles_equal(a.get('color' if key=='color_family' else key),key,wanted),'Wrong '+key+' on '+a['text']+': '+str(a.get(key)))
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

    # Additional independent checks for the 150-request corpus.
    if 'image_count' in expect:
        check(len(after['letters']['panels'])==expect['image_count'],'Wrong image count')
    if expect.get('no_duplicate_letters'):
        names=[a['text'].casefold() for p in after['letters']['panels'] for a in p['letters']]
        check(len(names)==len(set(names)),'Duplicate visible panel letters')
    if 'selected_groups' in expect:
        check(sorted(after['selection'].get('selected_group_paths',[]))==sorted(expect['selected_groups']),'Wrong selected groups')
    if expect.get('selection_empty'):
        check(not after['selection'].get('selected_panels') and not after['selection'].get('selected_group_paths'),'Selection was not cleared')
    if 'reverse_row' in expect:
        wanted=[list(r) for r in before['rows']]
        wanted[expect['reverse_row']-1].reverse()
        check(after['rows']==wanted,'Wrong reversed row order')
    if 'expected_order_indices' in expect:
        check([p['filename'] for p in after['letters']['panels']]==[before['letters']['panels'][i]['filename'] for i in expect['expected_order_indices']],'Wrong combined-operation image order')
    if 'scale_bars' in expect:
        check(sum(a['type']=='ScaleBar' for a in after['annotations'])==expect['scale_bars'],'Wrong scale-bar count')
    def by_ref(snapshot,ref):
        for p in snapshot['letters']['panels']:
            if any(a['text'].casefold()==str(ref).casefold() for a in p['letters']):return p['panel_id']
        return str(ref) if '/' in str(ref) else None
    images={p['panel_id']:p for p in after.get('images',[])}
    old_images={p['panel_id']:p for p in before.get('images',[])}
    for spec in expect.get('image_properties',[]):
        pid=by_ref(after,spec['ref']);actual=images.get(pid)
        check(actual is not None,'Missing image target '+spec['ref'])
        if actual:
            for key,wanted in spec.items():
                if key=='ref':continue
                got=actual.get(key)
                if key=='theta' and got is None:got=0
                if isinstance(wanted,(int,float)):
                    check(isinstance(got,(int,float)) and abs(got-wanted)<1e-5,'Wrong image '+key+' on '+spec['ref'])
                else:check(got==wanted,'Wrong image '+key+' on '+spec['ref'])
    for axis in ('h','v'):
        if expect.get('flip_'+axis):
            pid=by_ref(after,expect['flip_'+axis])
            old=old_images.get(pid,{})
            current=images.get(pid,{})
            source_unchanged=bool(old.get('pixel_digest')) and current.get('pixel_digest')==old['pixel_digest']
            native_flip=current.get('flip_'+axis) is True and source_unchanged
            legacy_flip=bool(old.get('flip_'+axis+'_digest')) and current.get('pixel_digest')==old['flip_'+axis+'_digest']
            check(native_flip or legacy_flip,'Displayed pixels were not flipped '+axis)
    for spec in expect.get('annotations_match',[]):
        pid=by_ref(after,spec.get('ref')) if spec.get('ref') else None
        if spec.get('ref') and pid is None:
            check(False,'Missing annotation owner '+spec['ref']);continue
        candidates=[a for a in after['annotations'] if (pid is None or a['panel_id']==pid) and (not spec.get('type') or a['type']==spec['type']) and (not spec.get('text') or a.get('text')==spec['text'])]
        check(len(candidates)==spec.get('count',1),'Wrong requested annotation count '+str(spec))
        if candidates:
            a=candidates[-1]
            for key in ('kind','color','fill_color','stroke'):
                if key in spec:check(a.get(key)==spec[key],'Wrong annotation '+key)
            if 'color_family' in spec:check(styles_equal(a.get('color'),'color_family',spec['color_family']),'Wrong annotation color family')
            if 'geometry' in spec:
                check(all(abs(x-y)<1e-4 for x,y in zip(a.get('geometry',[]),spec['geometry'])) and len(a.get('geometry',[]))==4,'Wrong ROI geometry')
            for key,wanted in spec.get('style',{}).items():
                check(styles_equal(a.get('style',{}).get(key),key,wanted),'Wrong annotation text '+key)
    for spec in expect.get('image_field_changed',[]):
        pid=by_ref(after,spec['ref'])
        check(pid is not None and images.get(pid,{}).get(spec['field'])!=old_images.get(pid,{}).get(spec['field']),'Unchanged image '+spec['field']+' on '+spec['ref'])
    for wanted in expect.get('document_contains',[]):
        check(any(wanted.casefold() in s.casefold() for s in after.get('document_strings',[])),'Text missing from document: '+wanted)
    if expect.get('preserve_other_image_properties'):
        targets={by_ref(before,r) for r in expect['preserve_other_image_properties']}
        for pid,old in old_images.items():
            if pid not in targets:check(images.get(pid)==old,'Unrequested image-property change on '+pid)
    for key,wanted in expect.get('caption',{}).items():
        actual=(after.get('caption') or {}).get(key)
        check(caption_markup_equal(actual,wanted) if key=='caption_markdown' else actual==wanted,'Wrong caption '+key)
    if 'plot_count' in expect:check(sum(p.get('is_plot',False) for p in images.values())==expect['plot_count'],'Wrong rendered plot count')
    for filename in expect.get('filename_contains',[]):
        check(any(filename in p['filename'] for p in images.values()),'Imported image missing: '+filename)
    if 'all_row_spacing' in expect:
        check(all(abs(float(r.get('space') or 0)-expect['all_row_spacing'])<1e-4 for r in after.get('row_settings',[])),'Wrong within-row spacing')
    for spec in expect.get('output_files',[]):
        from pathlib import Path
        file=Path(spec['path'])
        check(file.is_file() and file.stat().st_size>0,'Missing output file '+str(file))
        if file.is_file():
            data=file.read_bytes()
            if spec.get('format')=='png':check(data.startswith(bytes.fromhex('89504e470d0a1a0a')),'Invalid PNG output')
            if spec.get('format')=='pdf':check(data.startswith(b'%PDF'),'Invalid PDF output')
            if spec.get('format')=='svg':
                import xml.etree.ElementTree as ET
                try:check(ET.fromstring(data).tag.endswith('svg'),'Invalid SVG root')
                except ET.ParseError:check(False,'Malformed SVG output')
            if spec.get('format')=='pyf':
                import xml.etree.ElementTree as ET
                try:ET.fromstring(data)
                except ET.ParseError:check(False,'Malformed PYF output')
            if spec.get('contains'):check(spec['contains'] in data.decode('utf-8',errors='replace'),'Output content missing')


    attempts=[]
    pending=[]
    for kind,value in events:
        if kind=='tool_call':
            args=value.get('arguments',{})
            name=args.get('tool_name','') if value.get('name')=='use_pyfigures_tool' else value.get('name','')
            read_only = name == 'simulate_color_blindness' or any(word in name for word in ('inspect','find_','get_','list_','preview','select_live','open_annotation','explain_','show_me_how','guidance','check_','audit_','describe_','review_submission','figure_review_brief'))
            item={'name':name,'refused':False,'completed':False,'read_only':read_only}
            attempts.append(item)
            pending.append(item)
        elif kind=='tool_result' and pending:
            # Engine emits call/result pairs sequentially; a result must match its call.
            item=pending.pop(0)
            item['completed']=True
            item['refused']=bool(value.get('is_error'))
    edits=[a['name'] for a in attempts if a['name'] and not a['read_only'] and not a['refused']]
    refused=[a['name'] for a in attempts if a['name'] and not a['read_only'] and a['refused']]
    check(all(name in allowed for name in edits),'Unexpected mutation operation: '+str(edits))
    # Refusal does not prove no change. Existing no-edit document/caption digests and
    # all requested property/preservation checks above still run independently.
    check(all(name in allowed for name in refused),'Efficiency: Disallowed refused mutation attempt: '+str(refused))
    check(len(edits)+len(refused)<=expect.get('max_mutations',1),'Efficiency: Too many mutation calls: '+str(edits+refused))
    if 'font_reply' in expect:
        failures+=verify_font_reply(expect['font_reply'],after,events)
    failures+=verify_advanced(expect,before,after)
    if expect.get('clarification'):check('?' in replies or any(word in replies for word in ('which','clarify','specify','choose')),'No clarification question')
    return failures


"""Independent rich-text and live editor-draft assertions."""
def verify_advanced(expect,before,after):
    failures=[]
    def check(value,message):
        if not value:failures.append(message)
    def panel_id(ref):
        return next((p['panel_id'] for p in before['letters']['panels'] if p['panel_id']==ref or any(a['text']==ref for a in p['letters'])),None)
    def characters(annotation):
        result={}
        for run in annotation.get('runs',[]):
            position=run['start']
            style={k:v for k,v in run.items() if k not in ('start','length','text')}
            for char in run['text']:
                result[position]=style
                position+=len(char.encode('utf-16-le'))//2
        return result
    for spec in expect.get('text_spans',[]):
        pid=panel_id(spec['ref'])
        matches=[a for a in after['annotations'] if a['panel_id']==pid and a.get('text')==spec['text']]
        check(len(matches)==1,'Text span target not unique or wording changed')
        if len(matches)!=1:continue
        actual=matches[0];mapping=characters(actual)
        positions=[];start=0
        while True:
            start=spec['text'].find(spec['match'],start)
            if start<0:break
            positions.append(start);start+=len(spec['match'])
        occurrence=spec.get('occurrence',1)
        if not 1<=occurrence<=len(positions):
            failures.append('Text span match missing');continue
        pos=positions[occurrence-1]
        start=len(spec['text'][:pos].encode('utf-16-le'))//2
        end=start+len(spec['match'].encode('utf-16-le'))//2
        wanted={k:v for k,v in spec.items() if k not in ('ref','text','match','occurrence','preserve_outside')}
        chosen=[fmt for position,fmt in mapping.items() if start<=position<end]
        check(bool(chosen) and all(all(fmt.get(k)==v for k,v in wanted.items()) for fmt in chosen),'Wrong selected rich-text formatting')
        if spec.get('preserve_outside'):
            previous=next((a for a in before['annotations'] if a['panel_id']==pid and a['index']==actual['index']),None)
            check(previous is not None,'Original rich-text annotation missing')
            if previous:
                old=characters(previous)
                check(all(fmt==old.get(position) for position,fmt in mapping.items() if not start<=position<end),'Unrequested rich-text formatting changed')
    for spec in expect.get('editor_annotations_match',[]):
        found=[a for a in after.get('editor_annotations',[]) if a['type']==spec['type'] and (not spec.get('selected') or a.get('selected'))]
        check(len(found)==1,'Native editor annotation selection is not unique')
        if len(found)==1:
            for key,value in spec.items():
                check(found[0].get(key)==value,'Wrong editor draft '+key)
    if 'preserve_editor_except' in expect:
        permitted=set(expect['preserve_editor_except'])|{'token'}
        old={a['annotation_index']:a for a in before.get('editor_annotations',[])}
        for a in after.get('editor_annotations',[]):
            previous=old.get(a['annotation_index'])
            if previous is None:failures.append('Editor unexpectedly added an annotation');continue
            allowed=permitted if a.get('selected') else set()
            check({k:v for k,v in a.items() if k not in allowed}=={k:v for k,v in previous.items() if k not in allowed},'Editor changed unrequested properties')
    if expect.get('open_dialog_title'):
        check(expect['open_dialog_title'] in after.get('open_dialogs',[]),'Requested native property dialog is not open')
    if expect.get('clarification'):
        # The caller checks replies separately; this flag also requires no mutation.
        check(before['document_digest']==after['document_digest'],'Clarification request changed the figure')
    return failures


def verify_font_reply(spec,after,events):
    """Availability comes from the GUI font database, never the model's claim."""
    import re
    failures=[]
    replies=' '.join(str(v) for k,v in events if k=='assistant').lower()
    plain=re.sub('[*_#'+chr(96)+']','',replies)
    calls=[]
    for kind,value in events:
        if kind!='tool_call':continue
        args=value.get('arguments',{})
        name=args.get('tool_name') if value.get('name')=='use_pyfigures_tool' else value.get('name')
        args=args.get('arguments',{}) if value.get('name')=='use_pyfigures_tool' else args
        if name=='list_fonts':calls.append(args)
    if spec['kind']=='inventory':
        if not any(not c.get('query') for c in calls):failures.append('Font inventory not read with list_fonts()')
        if not re.search(r'\bfonts?\b|\bfamil(?:y|ies)\b',plain):failures.append('No font inventory explanation')
        return failures
    query=spec['query']
    status=after.get('font_status',{}).get(query)
    if not status:return ['Missing independent font status for '+query]
    if spec['kind']=='query' and not any(str(c.get('query','')).casefold()==query.casefold() for c in calls):
        failures.append('Font query not checked using exact requested family')
    if query.lower() not in plain:failures.append('Requested font missing from reply')
    if status['installed']:
        if spec['kind']=='query':
            if not re.search(r'\binstalled\b|\bavailable\b',plain):failures.append('No installed-font answer')
            if re.search(r'\b'+re.escape(query.lower())+r'\b[^\n.!?]{0,70}\b(?:not|isn.t)\s+(?:currently\s+)?(?:installed|available)\b',plain) or re.search(r'\b(?:font_check\.)?installed\s*:\s*false\b',plain):
                failures.append('Installed font wrongly described as missing')
    else:
        if not re.search(r'\b(?:not|isn.t|is not|unavailable|missing|doesn.t|does not|no)\b',plain):
            failures.append('Missing font not disclosed')
        if str(status.get('drawn_as','')).lower() not in plain:
            failures.append('Actual drawn/exported font missing from reply')
        alternatives=status.get('alternatives',[])
        if alternatives and not any(a.lower() in plain for a in alternatives):
            failures.append('No installed font alternative offered')
        if not re.search(r'\bdraw\w*|\bexport\w*|\brender\w*|\bsubstitut\w*|\bfallback\b|\breplac\w*',plain):
            failures.append('Font substitution behavior not explained')
    return failures
