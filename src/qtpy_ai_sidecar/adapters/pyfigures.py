"""Optional HTTP adapter to the existing isolated PyFigures prototype.

No PyFigures imports, source edits, monkey patches, or file-based figure editing.
The existing bridge marshals requests onto the application's Qt thread.
"""
import json
from pathlib import Path
import uuid
import urllib.request


class PyFiguresAdapter:
    supports_preview = True

    def __init__(self, descriptor):
        self.descriptor = Path(descriptor)

    def request(self, operation, arguments=None):
        connection = json.loads(self.descriptor.read_text())
        from urllib.parse import urlsplit
        url = urlsplit(connection['url'])
        if url.hostname not in ('127.0.0.1', 'localhost', '::1'):
            raise ValueError('The PyFigures bridge must be local')
        data = json.dumps({'operation': operation, 'arguments': arguments or {},
                           'request_id': str(uuid.uuid4())}).encode()
        req = urllib.request.Request(connection['url'], data,
            headers={'Authorization': 'Bearer ' + connection['token'], 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=45) as response:
            result = json.load(response)
        if 'error' in result:
            raise RuntimeError(result['error'])
        return result['result']

    @staticmethod
    def decorate(record):
        status = record.get('status')
        controls = []
        if record.get('changed'):
            if status == 'undone':
                controls = ['redo']
            elif record.get('preview') and status in ('preview', 'interrupted'):
                controls = ['apply', 'discard']
            elif status == 'applied' or (status == 'interrupted' and not record.get('preview')):
                controls = ['undo']
        return {**record, 'controls': controls}

    def context(self):
        result = self.request('inspect')
        return {key: result.get(key) for key in ('selection', 'verified_letter_specification', 'panel_references', 'text_annotations', 'last_canvas_click', 'annotation_editor_status', 'native_gui_jobs', 'native_gui_available', 'revision', 'dirty')}

    def context_instructions(self, state):
        selection = state.get('selection') or {}
        return ('If a capability is missing from dedicated MCP tools, discover inspect_native_gui and inspect the actual native controls instead of concluding the GUI cannot do it. Use_native_gui takes only inspected IDs and exact choices. Native context/drag menus are available via open_native_menu; keyboard, canvas gestures and file drops have native_gui tools. Prefer dedicated semantic tools for common edits. '
                'Native GUI calls return queued jobs, not success. Inspect native_gui jobs and active modal controls, fill native fields and accept/cancel as requested, then verify actual document state. Do not claim queued or running work has completed. Teaching requests still do not authorize using edit controls. '
                'How-to/manual/shortcut questions are teaching requests, not permission to edit. For native arrow keys and drag/drop discover explain_live_interaction; include figure focus, selection level, source/target and relevant verified shortcuts. For other topics use authored explain_how/show_me_how. Never invent modifiers or menu labels. Never provide Python unless code or recipe was explicitly requested. '
                'Use find_pyfigures_tools for the exact schema before a first use; state field names are not function argument names. remove_annotation uses group_path/image_index/annotation_index, not panel_id. open_annotation_editor uses panel_ref, not panel_id. edit_panel_letters has no letters or style object arguments: pass its flat schema fields. A mixed colour summary is not a valid colour; omit styling to preserve actual styles. '
                'Convert an existing ROI into an inset with roi_to_inset: this magnifies the same source, no external filename required. If multiple ROIs exist ask which; do not redefine the already clear request. '
                'If a user reports an invisible letter, inspect its appearance and location; existence in state does not prove visibility. Avoid categorical denials based on letter counts alone. '
                'For lettering a newly constructed figure, use one renumber/all operation for a complete unique sequence. Partial restore preserves earlier IDs. verified_letter_specification.duplicate_letter_references reports ambiguities; a correct count alone does not prove usable panel references. Never silently rename accepted manual labels. '
                'PANEL LETTERS and TEXT ANNOTATIONS are different objects. panel_references.letters are automatic panel IDs; text_annotations lists ordinary text with actual annotation_index and is_letter=false. '
                'A quoted string or the word text/caption means an ordinary annotation: match its actual text, then use get_annotations/remove_annotation at that index. Example: remove the Panel o text from panel o removes text=Panel o and PRESERVES letter=o. Do not search remove letter or call edit_panel_letters for that request. '
                'Only explicit letter requests use edit_panel_letters. To restore a missing letter on one panel use action=restore, scope=panels, panel_ids=[its ID], start_letter=the desired letter; style does not restore a hidden letter. '
                'removal_request is a literal quote of the human request, never a rewritten instruction invented to pass validation. On a tool exception inspect and explain the failure; changing file paths cannot fix an internal exception. '
                'Select actual GUI targets with select_live_objects (panel_refs for letters/IDs, row_numbers starting at 1, or group_paths for rows/columns). For a named row reversal select that row then reverse_selected_row. '
                'A general request to annotate/add annotations to a panel specifies no annotation content. Select the panel, then ask what to add or offer to open_annotation_editor. Never invent a placeholder annotation. Explicit open-editor requests use open_annotation_editor, which selects its panel and schedules the native dialog; do not claim annotations were added. '
                'Swap named panels/images by default: swap b and c means exchange image panels, including obvious connector typos. Use swap_live_panels target=images. Only exchange letter TEXT when explicitly requested. Ask only if target references do not uniquely resolve. '
                'For whole-row swaps discover swap_rows; use visible row numbers starting at 1. Never simulate row swaps using move_image. With automatic lettering enabled, row swaps regenerate letters in positional order, like native keyboard rearrangement; retain styles, not old letter text. '
                'last_canvas_click contains the last actual canvas press. For clicked/here ROI or arrow requests use its image_position only when valid=true and panel_id matches the intended panel; otherwise ask for a fresh click. Never treat scene/widget coordinates as image pixels. A click gives a point, not ROI width/height; clarify missing dimensions. '
                'Fresh PyFigures selection supersedes earlier focus. This/selected/current letter means the letter on the selected panel. '
                'If selected_panels contains exactly one entry, use that panel_id immediately; do not ask which letter. '
                'For letter styling use edit_panel_letters scope=panels with that panel_ids list, or scope=selection; preserve all unspecified properties. '
                'A named target or explicit all/group request overrides implicit selection. Selected rows/columns are groups; image2d, scripted and vector panels are valid targets. '
                'For selected annotations use their owner_panel_id only when the request concerns the owner. '
                'If selection is missing, stale or ambiguous ask for clarification. '
                'Follow-up it/them keeps this focus; color-only corrections must not change font, placement, background or numbering. A preview is displayed only to the human: this model cannot inspect image pixels. Property readback does not prove contrast/readability; never claim a color ensures visibility without a real check. Current focus: ' + str({'kind': selection.get('selection_kind'), 'panels': [p.get('panel_id') for p in selection.get('selected_panels', [])],
                                        'groups': selection.get('selected_group_paths', [])}))

    def validate_tool_call(self, tool_name, arguments, state, text):
        import re
        selection = state.get('selection') or {}
        panels = selection.get('selected_panels') or []
        explicit_target = re.search(r'\b(?:all|every|whole|entire)\b|\b(?:panel|letter)\s+(?:[a-z]|[0-9]+(?:/[0-9]+)?)\b', text, re.I)
        singular = re.search(r'\b(?:one|a|single|this|that|the)\s+(?:panel\s+)?(?:letter|label)\b', text, re.I)
        operation = arguments.get('tool_name') if tool_name == 'use_pyfigures_tool' else tool_name
        if operation=='review_submission_readiness':self._quality_review_requested=True
        vague_annotation = re.search(r'\bannot\w*\b', text, re.I) and not re.search(
            r'\b(?:arrow\w*|roi\w*|rectangle|ellipse|circle|polygon|line|text|label|scale|remove|delete|clear)\b|["]', text, re.I)
        if vague_annotation and operation in ('add_annotation', 'add_roi_rect', 'add_roi_ellipse', 'add_roi_line', 'add_roi_polygon', 'add_arrow'):
            from ..errors import NeedsClarification
            named = re.search(r'\bpanel\s+([a-z]|[0-9]+(?:/[0-9]+)*)(?!\w)', text, re.I)
            target = 'panel ' + named[1] if named else 'this panel'
            raise NeedsClarification(f'What would you like to add to {target}?\n- Tell me the annotation you want for {target}\n- Open the annotation editor for {target}\nNo annotation was added.')
        read_only = operation and (operation.startswith(('inspect_', 'get_', 'list_', 'check_', 'describe_', 'audit_', 'explain_')) or operation in ('preview_figure', 'find_pyfigures_tools', 'readability'))
        args = arguments.get('arguments', {}) if tool_name == 'use_pyfigures_tool' else arguments
        columns=re.search(r'(?<![\w.])(-?\d+)\s+(?:pictures?|images?|panels?)\s+(?:per|on each|in each|in a|a)\s+row\b',text,re.I)
        if columns and operation=='arrange_live_images' and args.get('columns')!=int(columns[1]):
            from ..errors import NeedsClarification
            raise NeedsClarification('The requested number of images per row is '+columns[1]+'. I cannot substitute a different count; please choose a valid positive number. No replacement layout was submitted.')
        point_sizes=list(re.finditer(r'(?<![\w.])(minus\s+|negative\s+)?(-?\d+(?:\.\d+)?)\s*(?:pt|points?)\b',text,re.I))
        relative_size=re.search(r'\b(?:by|increase|decrease|reduce|shrink|grow|bigger|smaller|larger|less|more|add|subtract)\b',text,re.I)
        point_size=point_sizes[0] if len(point_sizes)==1 and not relative_size else None
        if point_size and operation in ('edit_panel_letters','restyle_texts') and args.get('font_size') is not None:
            requested=float(point_size[2])*(-1 if point_size[1] else 1)
            if float(args['font_size'])!=requested:
                from ..errors import NeedsClarification
                raise NeedsClarification('The requested font size is '+str(requested)+' points. I cannot silently change its sign or size; please choose a valid positive size. No replacement style was submitted.')
        if singular and not explicit_target and (len(panels) != 1 or selection.get('stale_selection')) and not read_only:
            from ..errors import NeedsClarification
            raise NeedsClarification('Please select the panel with the hard-to-see letter, or tell me its panel label. I cannot identify which one from the current selection. No lettering edit was submitted.')
        focused = re.search(r'\b(?:this|selected|current)\s+(?:panel\s+)?(?:letter|label)\b', text, re.I)
        explicit = re.search(r'\b(?:all|every|whole|entire)\b|\bpanel\s+(?:[a-z]|[0-9]+(?:/[0-9]+)?)\b', text, re.I)
        focused = focused or re.search(r'\b(?:it|that|them)\b', text, re.I)
        if explicit or not focused or len(panels) != 1 or selection.get('stale_selection'):
            return
        name = arguments.get('tool_name') if tool_name == 'use_pyfigures_tool' else tool_name
        args = arguments.get('arguments', {}) if tool_name == 'use_pyfigures_tool' else arguments
        if name == 'edit_panel_letters' and args.get('panel_ids') and 'scope' not in args:
            args['scope'] = 'panels'
        if name == 'set_panel_letter_position':
            raise ValueError('Selected-letter request: use edit_panel_letters at selection/panels scope, not global position.')
        if name == 'edit_panel_letters':
            scope = args.get('scope', 'all')
            if scope == 'selection':
                return
            if scope == 'panels' and args.get('panel_ids') == [panels[0]['panel_id']]:
                return
            raise ValueError('Selected-letter request targets only panel ' + panels[0]['panel_id'] + '; no edit submitted. Use scope=selection or that panel_ids list.')

    @staticmethod
    def _color_request(text):
        import re
        if re.search(r'\b(background|fill|opacity|move|position|size|font|bold|italic|underline|rename|renumber|remove|restore|swap|and|then)\b', text, re.I):
            return None
        colors = {'white':'#ffffff', 'black':'#000000', 'blue':'#0000ff', 'red':'#ff0000', 'green':'#008000', 'yellow':'#ffff00'}
        found = re.findall(r'\b(?:white|black|blue|red|green|yellow)\b|#[0-9a-f]{6}\b', text.lower())
        unique = set(found)
        if len(unique) != 1:
            return None
        name = found[0]
        return name, colors.get(name, name)

    def verified_completion(self, tool_name, arguments, result, state, text):
        import re
        name = arguments.get('tool_name') if tool_name == 'use_pyfigures_tool' else tool_name
        if name == 'swap_rows' and not result.get('is_error'):
            match = re.fullmatch(r'\s*(?:please\s+)?(?:swap|exchange|switch)\s+rows?\s+(\d+)\s+(?:and|with)\s+(?:row\s+)?(\d+)[.!? ]*', text, re.I)
            if match:
                try:
                    body = json.loads(result.get('content', ''))
                    op = body.get('operation_result') or {}
                    pair = {int(match[1]), int(match[2])}
                    if op.get('completion_verified') and op.get('action') == 'swap_rows' and {op.get('first_row'),op.get('second_row')} == pair:
                        mode = 'Automatic letters updated to their new positions.' if op.get('lettering_mode') == 'automatic_position' else 'Existing letter text preserved (automatic lettering off).'
                        return f"Rows {int(match[1])} and {int(match[2])} swapped. {mode} Image order within each row and letter styling preserved; verified in the open figure." 
                except (ValueError, TypeError):
                    pass
        request = self._color_request(text)
        if not request or result.get('is_error'):
            return None
        name = arguments.get('tool_name') if tool_name == 'use_pyfigures_tool' else tool_name
        if name != 'edit_panel_letters':
            return None
        try:
            body = json.loads(result.get('content', ''))
        except (ValueError, TypeError):
            return None
        operation = body.get('operation_result') or {}
        ids = operation.get('matched_panel_ids') or []
        expected = [p['panel_id'] for p in (state.get('selection') or {}).get('selected_panels', [])]
        import re
        all_requested = bool(re.search(r'\b(?:all|every)\b', text, re.I))
        if all_requested and len(ids) != (state.get('verified_letter_specification') or {}).get('image_panels'):
            return None
        if not ids or (not all_requested and (not expected or set(ids) != set(expected))):
            return None
        if any(c.get('property') != 'color' for c in operation.get('verified_changes', [])):
            return None
        panels = {p['panel_id']: p for p in operation.get('verified_panels', [])}
        for p in (body.get('selection') or {}).get('selected_panels', []):
            panels.setdefault(p['panel_id'], {'letters':p.get('letter_styles', [])})
        if any(i not in panels or not panels[i].get('letters') or any(str(a.get('color')).lower() != request[1] for a in panels[i]['letters']) for i in ids):
            return None
        target = 'The letter on panel ' + ids[0] if len(ids) == 1 else str(len(ids)) + ' panel letters'
        verb = ' is' if len(ids) == 1 else ' are'
        return target + verb + (' already ' if not operation.get('changed') else ' now ') + request[0] + '. Verified in the open figure.'

    def finalize_manual_response(self,request):
        import re
        manual=bool(re.search(r'\b(?:how|explain|tutorial|instructions?|shortcuts?)\b|\bwhere\s+(?:do|can|should)\b',request,re.I))
        if not manual:return None
        positive=re.sub(r"\b(?:without|no|do not|don't)\s+(?:any\s+)?(?:using\s+)?(?:python|code|recipes?|scripts?)\b",'',request,flags=re.I)
        if re.search(r'\b(?:code|python|recipes?|scripts?)\b',positive,re.I):return None
        try:
            guide=self.request('manual_guide',{'topic':request})
        except Exception:
            return None
        if guide.get('status') not in ('explained','source_reviewed'):return None
        steps=guide.get('steps')
        if not steps and guide.get('guides'):
            steps=[s for g in guide['guides'] for s in g.get('steps',[])]
        if not steps:return None
        # A broad export keyword must not turn a PDF question into PPTX steps.
        if guide.get('guide')=='export_pptx' and not re.search(r'powerpoint|pptx|\bppt\b',request,re.I):return None
        title=guide.get('title') or 'In PyFigures'
        content=title+':\n\n'+'\n'.join(str(i+1)+'. '+step for i,step in enumerate(steps))
        if guide.get('guide')=='reorder_panels':
            content+='\n\nWith automatic lettering enabled, letters follow panel positions.'
        return {'content':content,'evidence':{'kind':'authored_manual_guide','guide':guide,'operation_executed':False}}

    def finalize_response(self,request,reply,state,preview=False):
        import re
        manual=self.finalize_manual_response(request)
        if manual:return manual
        if re.search(r'\b(?:how|tutorial|instructions|shortcut)\b',request,re.I):return None
        asks_ready=bool(re.search(r'\b(?:ready|readiness)\b',request,re.I) and
                        re.search(r'\b(?:is|are|whether|tell|check|review|submission|publication|submit)\b',request,re.I))
        asks_compliance=bool(re.search(r'\b(?:check|review|assess|audit)\b.*\b(?:compliance|print resolution|submission)\b',request,re.I))
        asks_publication=bool(re.search(r'\b(?:can|could|would|should)\b.*\b(?:submit|publish)\b',request,re.I))
        if not (asks_ready or asks_compliance or asks_publication or getattr(self,'_quality_review_requested',False)):return None
        try:
            evidence=self.request('submission_review',{})
        except Exception as exc:
            return {'content':'Technical readiness could not be verified: '+str(exc),
                    'evidence':{'status':'incomplete','error':str(exc)}}
        title='Draft' if preview else 'Current figure'
        if evidence['status']=='blocked':
            lines=[re.sub(r'^\[FAIL\]\s*','',b) for b in evidence.get('blockers',[])]
            content=title+' is not ready under the technical checks:\n'+''.join('\n- '+line for line in lines)
        elif evidence['status']=='technical_checks_passed':
            target_line=evidence.get('checks',{}).get('check_resolution',{}).get('report','').splitlines()
            content=title+' passes the measured technical checks for this target. '+(target_line[0] if target_line else '')+' Scientific content and statistical assumptions still require review.'
        else:
            content='Technical readiness is incomplete; no ready verdict can be given. Specify a valid journal/physical target and resolve unavailable checks.'
        return {'content':content,'evidence':evidence}

    def begin(self, text, preview=False):
        self._quality_review_requested=False
        return self.request('action_begin', {'text': text, 'preview': preview})

    def finish(self, interrupted=False):
        return self.decorate(self.request('action_finish', {'interrupted': interrupted}))

    def control(self, action, ident=None):
        if action not in ('undo', 'redo', 'apply', 'discard', 'recover'):
            raise ValueError('Unsupported host control')
        return self.decorate(self.request('action_' + action, {'ident': ident} if ident else {}))


def attach_to_window(window, config, descriptor):
    """Embed this package in a running PyFigures prototype main window."""
    from qtpy.QtCore import Qt
    from qtpy_ai_sidecar import create_dock
    from qtpy_ai_sidecar.branding import application_icon
    dock = create_dock(window, config, PyFiguresAdapter(descriptor))
    dock.setWindowIcon(application_icon())
    dock.setMinimumWidth(320)
    dock.setMaximumWidth(560)
    # Message/choice size hints must never steal the host canvas width.
    from qtpy.QtCore import QObject, QEvent
    class WidthGuard(QObject):
        def eventFilter(self, obj, event):
            if event.type() == QEvent.Type.Resize:
                cap = max(280, min(560, int(obj.width() * 0.4)))
                dock.setMinimumWidth(min(320, cap))
                dock.setMaximumWidth(cap)
            return False
    dock._width_guard = WidthGuard(window)
    window.installEventFilter(dock._width_guard)
    dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
    window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
    dock.setFloating(False)
    window.local_chat_dock = dock
    window.resize(max(window.width(), 1400), max(window.height(), 850))
    window.resizeDocks([dock], [480], Qt.Orientation.Horizontal)
    return dock
