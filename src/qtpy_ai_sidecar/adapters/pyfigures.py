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
        payload={'operation':operation,'arguments':arguments or {},'request_id':str(uuid.uuid4())}
        if operation in ('inspect_annotation_objects','letter_state','select_live_objects'):
            current=self.request('inspect')
            payload.update(session_id=current['session_id'],expected_revision=current['revision'])
        data=json.dumps(payload).encode()
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

    def read_cache_epoch(self):
        # A cheap host stamp prevents reuse after an external selection/document change.
        import hashlib
        state=self.request('inspect')
        value={k:state.get(k) for k in ('session_id','revision','selection','native_gui_jobs','last_canvas_click')}
        if state.get('annotation_editor_open'):
            value['editor']=self.request('inspect_annotation_objects')
        return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()

    def is_read_only_call(self, tool_name, arguments):
        # Exact pure observations, not name prefixes or merely non-document GUI actions.
        pure={'inspect_figure','inspect_native_gui','inspect_annotation_objects',
              'inspect_panel_letters','get_annotations','get_figure_caption',
              'get_figure_properties','list_how_to_guides','explain_how',
              'explain_live_interaction','find_pyfigures_tools',
              'list_pyfigures_categories','list_fonts','preview_panel','preview_luts',
              'search_images'}
        if tool_name=='use_pyfigures_tool':
            return arguments.get('tool_name') in pure
        if tool_name in pure:return True
        if tool_name in ('select_live_objects','undo_redo','show_me_how','close_guidance',
                         'open_annotation_editor','open_annotation_properties',
                         'open_native_menu','use_native_gui','native_gui_keys',
                         'native_gui_gesture','native_gui_drop_files'):
            return False
        return None  # Other connected services need their own explicit MCP hint.


    def context(self):
        result = self.request('inspect')
        summary = result.get('figure_summary') or {}
        if summary.get('empty'):     # a short state lets the model answer without any tool step
            return {'figure_summary': summary, 'native_gui_available': result.get('native_gui_available'),
                    'revision': result.get('revision'), 'dirty': result.get('dirty')}
        context = {key: result.get(key) for key in ('figure_summary', 'selection', 'verified_letter_specification', 'panel_references', 'text_annotations', 'roi_annotations', 'last_canvas_click', 'annotation_editor_status', 'native_gui_jobs', 'native_gui_available', 'revision', 'dirty')}
        if result.get('annotation_editor_open'):
            context['annotation_editor']=self.request('inspect_annotation_objects')
        return context

    def context_instructions(self, state):
        selection = state.get('selection') or {}
        if (state.get('figure_summary') or {}).get('empty'):
            return ('The figure is empty. For questions about it, reply at once from figure_summary (answer and how_to_add_content), '
                    'without tools. For a request to add content, discover the tool with find_pyfigures_tools.')
        return ('This state is current: answer "what is in the figure?" from figure_summary and panel_references without calling inspect_figure again; '
                + ('preview_figure only when asked how it looks. ' if not getattr(self, 'vision', False) else 'preview_figure when the look matters. ') +
                'When annotation_editor is present, editor_draft_objects and selected=true describe the live editor selection. Edits there affect its draft until native OK; preserve Cancel. Use edit_annotation_properties with the CURRENT editor_draft_objects token, or inspected native controls. Main-object tokens describe the unchanged figure, not the draft. After each edit use its returned next_token; never reuse the pre-edit token or silently close the dialog. '
                'If a capability is missing from dedicated MCP tools, discover inspect_native_gui and inspect the actual native controls instead of concluding the GUI cannot do it. Use_native_gui takes only inspected IDs and exact choices. Native context/drag menus are available via open_native_menu; keyboard, canvas gestures and file drops have native_gui tools. Prefer dedicated semantic tools for common edits. '
                'Native GUI calls return queued jobs, not success. Inspect native_gui jobs and active modal controls, fill native fields and accept/cancel as requested, then verify actual document state. Do not claim queued or running work has completed. Teaching requests still do not authorize using edit controls. '
                'How-to/manual/shortcut questions are teaching requests, not permission to edit. For native arrow keys and drag/drop discover explain_live_interaction; include figure focus, selection level, source/target and relevant verified shortcuts. For other topics use authored explain_how/show_me_how. Never invent modifiers or menu labels. Never provide Python unless code or recipe was explicitly requested. '
                'For arrange_live_images, columns is the number of images per row; a row count is a different request. For set_figure_caption, caption is exact plain text including punctuation, title is separate, and caption_markdown is an optional formatted STRING, never a boolean. Use set_scale_bar with panel_ref for a single panel; set_scale_bar_all is only for a whole-figure request. '
                'Use find_pyfigures_tools for the exact schema before a first use; state field names are not function argument names. Native image/annotation tools prefer panel_ref for named panels. Text setters use text_index from inspection; ROI/removal tools use the full annotation_index. panel_id is not a setter argument. open_annotation_editor uses panel_ref, not panel_id. edit_panel_letters has no letters or style object arguments: pass its flat schema fields. A mixed colour summary is not a valid colour; omit styling to preserve actual styles. '
                'Convert an existing ROI into an inset with roi_to_inset: this magnifies the same source, no external filename required. If multiple ROIs exist ask which; do not redefine the already clear request. '
                'Is a font available? Use list_fonts(query=the_font), answer from font_check. '
                'Give a a scale bar names panel a, not all panels; bulk needs an explicit whole-figure request. Unknown-name suggestions require human confirmation. Report completed edits briefly using verified changes, not full state dumps unless asked. If a user reports an invisible letter, inspect its appearance and location; existence in state does not prove visibility. Avoid categorical denials based on letter counts alone. '
                'For lettering a newly constructed figure, use one renumber/all operation for a complete unique sequence. Partial restore preserves earlier IDs. verified_letter_specification.duplicate_letter_references reports ambiguities; a correct count alone does not prove usable panel references. Never silently rename accepted manual labels. '
                'For ordinary rich-text range formatting or ROI property edits, discover inspect_annotation_objects and edit_annotation_properties. Inspect the exact object and pass its token; do not replace whole formatted text to style one substring. Repeated text needs an explicit occurrence. Native dialogs keep OK/Cancel; finish them before direct annotation edits. '
                'PANEL LETTERS and TEXT ANNOTATIONS are different objects. panel_references.letters are automatic panel IDs; text_annotations lists ordinary text with actual annotation_index and is_letter=false. '
                'A direct write/type/put text-on-panel instruction supplies literal text even without quotation marks; ask for content only when it is actually missing. Respect ordered clauses: complete an earlier dependent edit before rearranging its target; if that edit needs clarification, pause dependent later mutations. '
                'Write/put <words> on <panel> supplies literal text even without quotes; dependent text precedes a swap. caption is exact plain text including any final period; title is separate and caption_markdown an optional formatted string. A quoted string or the word text/caption means an ordinary annotation: match its actual text, then use get_annotations/remove_annotation at that index. Example: remove the Panel o text from panel o removes text=Panel o and PRESERVES letter=o. Do not search remove letter or call edit_panel_letters for that request. '
                'For all letters use scope=all without panel_ids; panels scope requires panel_ids. For bold/italic/underline use restyle_texts(target=letters). Only explicit letter requests use edit_panel_letters. To restore a missing letter on one panel use action=restore, scope=panels, panel_ids=[its ID], start_letter=the desired letter; style does not restore a hidden letter. '
                'removal_request is a literal quote of the human request, never a rewritten instruction invented to pass validation. On a tool exception inspect and explain the failure; changing file paths cannot fix an internal exception. '
                'select_live_objects is directly available: clear=true clears the selection without panel_refs. Select actual GUI targets with panel_refs for letters/IDs, row_numbers starting at 1, or group_paths for rows/columns. For a named row reversal select that row then reverse_selected_row. '
                'A general request to annotate/add annotations to a panel specifies no annotation content. Select the panel, then ask what to add or offer to open_annotation_editor. Never invent a placeholder annotation. Explicit open-editor requests use open_annotation_editor, which selects its panel and schedules the native dialog; do not claim annotations were added. '
                'Swap IMAGE PANELS by default: swap b and c or put b in place of a and a in place of b means exchange images. Use swap_live_panels target=images. Letter TEXT swaps require an explicit swap-the-letters/labels request. If a reference is missing or non-unique, STOP and ask; never substitute an existing panel or retry with other references. '
                'A uniquely named panel wins over a positional/visual description; act on that name and mention the discrepancy. Never edit then undo to ask. '
                'For whole-row swaps discover swap_rows; use visible row numbers starting at 1. Never simulate row swaps using move_image. With automatic lettering enabled, row swaps regenerate letters in positional order, like native keyboard rearrangement; retain styles, not old letter text. '
                'last_canvas_click contains the last actual canvas press. For clicked/here ROI or arrow requests use its image_position only when valid=true and panel_id matches the intended panel; otherwise ask for a fresh click. Never treat scene/widget coordinates as image pixels. A click gives a point, not ROI width/height; clarify missing dimensions, except for a magnified inset at a click: roi_to_inset uses the click with its default box_size (120 px) unless a size was given. '
                'A pixel size the user states (e.g. "the pixel size is 1.24 µm") applies to every image the request covers, including panels whose pixel_size is None (None only means not calibrated yet): pass it as px_to_unit. '
                'Fresh PyFigures selection supersedes earlier focus. This/selected/current letter means the letter on the selected panel. '
                'If selected_panels contains exactly one entry, use that panel_id immediately; do not ask which letter. '
                'For letter styling use edit_panel_letters scope=panels with that panel_ids list, or scope=selection; preserve all unspecified properties. '
                'A named target or explicit all/group request overrides implicit selection. Selected rows/columns are groups; image2d, scripted and vector panels are valid targets. '
                'For selected annotations use their owner_panel_id only when the request concerns the owner. '
                'If selection is missing, stale or ambiguous ask for clarification. '
                'Follow-up it/them keeps this focus; color-only corrections must not change font, placement, background or numbering. ' + ('Previews are attached for you to inspect: look at the latest one before saying a visual edit is done. ' if getattr(self, 'vision', False) else 'A preview is displayed only to the human: this model cannot inspect image pixels. ') + 'Property readback does not prove contrast/readability; never claim a color ensures visibility without a real check. Current focus: ' + str({'kind': selection.get('selection_kind'), 'panels': [p.get('panel_id') for p in selection.get('selected_panels', [])],
                                        'groups': selection.get('selected_group_paths', [])}))


    @staticmethod
    def _efficient_arguments(operation, args, state):
        """Normalize only proven no-ops; never invent targets or authorization."""
        if operation == 'arrange_live_images' and 'rows' in args:
            raise ValueError('Use columns for images per row; rows is not an accepted argument. A number of rows and images per row mean different layouts. Inspect the schema; no layout was changed.')
        if operation == 'edit_annotation_properties':
            refs = state.get('panel_references', [])
            owners = [p['panel_id'] for p in refs if args.get('panel_ref') in [p['panel_id']] + p.get('letters', [])]
            if len(owners) == 1 and isinstance(args.get('annotation_index'), int) and not isinstance(args.get('annotation_index'), bool):
                editor = state.get('annotation_editor') or {}
                if state.get('annotation_editor_open') or editor.get('editor_open'):
                    objects = editor.get('editor_draft_objects', []) if editor.get('editor_panel_id') == owners[0] else []
                else:
                    objects = state.get('text_annotations', []) + state.get('roi_annotations', [])
                matches = [a for a in objects if a.get('panel_id', owners[0]) == owners[0] and a.get('annotation_index') == args['annotation_index']]
                if len(matches) == 1 and matches[0].get('token') and args.get('token') != matches[0]['token']:
                    raise ValueError('ANNOTATION_TOKEN_REQUIRED: No edit submitted. The current object at panel ' + owners[0] + ', annotation_index=' + str(args['annotation_index']) + ' has token=' + matches[0]['token'] + '. Use this object token, not a selection or another annotation token. If this is not the intended object, inspect_annotation_objects before retrying.')
        if operation == 'edit_panel_letters':
            extras = set(args) & {'opacity', 'bold', 'italic', 'underline'}
            if extras:
                scope = args.get('scope', 'auto')
                selected = (state.get('selection') or {}).get('selected_panels', [])
                targets = args.get('panel_ids') if scope in ('auto', 'panels') else [p['panel_id'] for p in selected] if scope == 'selection' else None
                styles = []
                if targets:
                    for target in targets:
                        matches = [p for p in selected if p.get('panel_id') == target and p.get('letter_styles')]
                        if len(matches) != 1:break
                        styles.extend(matches[0]['letter_styles'])
                    else:
                        if styles:
                            for field in list(extras):
                                if all(field in a and a[field] == args[field] for a in styles):args.pop(field)
                # A genuinely uniform whole-figure value also proves a subset's no-op.
                uniform = (state.get('verified_letter_specification') or {}).get('uniform_letter_style') or {}
                for field in extras & set(args):
                    if field in uniform and uniform[field] == args[field]:args.pop(field)
                unsupported = extras & set(args)
                if unsupported:
                    raise ValueError('Unsupported edit_panel_letters fields: ' + ', '.join(sorted(unsupported)) + '. Bold/italic/underline use restyle_texts(target=letters); opacity requires a supported discovered tool. No edit submitted; fields that would change state were not silently discarded.')



    @staticmethod
    def _named_panel_address_guard(operation, args, state, text):
        """Refuse proven named-panel/numeric-address conflicts without retargeting."""
        import re
        # Explicit family: schema-known panel mutations only, never an unknown tool.
        panel_operations = {
            'edit_panel_letters', 'style_annotation', 'set_annotation_text',
            'edit_annotation_properties', 'set_roi_properties', 'add_annotation',
            'remove_annotation', 'add_roi_rect', 'add_roi_ellipse', 'add_roi_line',
            'add_roi_polygon', 'add_arrow', 'set_scale_bar', 'remove_scale_bar',
            'set_image_property', 'set_lut', 'crop_image', 'rotate_image',
        }
        if operation not in panel_operations:
            return
        # A genuinely named reference goes through the existing native resolver.
        ref = args.get('panel_ref')
        if ref is not None and not re.fullmatch(r'[0-9]+(?:/[0-9]+)*', str(ref)):
            return
        # Quoted annotation contents can mention panel names without targeting them.
        source = re.sub(r'"[^"]*"|\x27[^\x27]*\x27', ' ', text)
        # "Leave every other letter alone" restricts the target; it names nothing to edit.
        source = re.sub(r'\b(?:leave|keep|preserve|(?:do\s+not|don\'?t)\s+(?:touch|change)|without\s+(?:touching|changing))\b[^.;!?]*', ' ', source, flags=re.I)
        # Do not infer the complete target set for relative, broader or exclusion requests.
        if re.search(r'\b(?:neighbou?rs?|adjacent|remaining|rest|except|excluding|all|every|each|whole|entire)\b|\bnext\s+to\b', source, re.I):
            return
        if re.search(r'\b(?:panels?|images?|pictures?|letters?|and|or)\s+(?:alpha|beta|gamma|delta|epsilon|zeta|eta|theta|iota|kappa|lambda|mu|nu|xi|omicron|pi|rho|sigma|tau|upsilon|phi|chi|psi|omega)\b', source, re.I):
            return
        names = []
        pattern = r'\b(?P<kind>panels?|images?|pictures?|letters?|select|pick|highlight|choose|annotate|rotate|unrotate|crop|delete|remove|style|move|swap|exchange|switch|make)\s+(?P<labels>[a-z](?!\w)(?:\s*(?:,|and|or|&)\s*[a-z](?!\w))*)'
        for found in re.finditer(pattern, source, re.I):
            labels = re.findall(r'\b[a-z]\b', found['labels'].lower())
            if 'a' in labels and found['kind'].lower() not in ('panel', 'panels', 'image', 'images', 'picture', 'pictures', 'letter', 'letters'):
                # After a verb, a may be an article. The full target set is uncertain.
                return
            names.extend(labels)
        names = list(dict.fromkeys(names))
        if not names:
            return
        panels = state.get('panel_references') or []
        requested = []
        for name in names:
            matches = [p for p in panels if name in [str(v).casefold() for v in p.get('letters', [])]]
            # Missing/duplicated labels remain the existing clarification path's job.
            if len(matches) != 1:
                return
            requested.append(matches[0])
        targets = []
        if 'panel_ids' in args:
            values = args['panel_ids']
            if not isinstance(values, list) or not values:
                return
            for value in values:
                if not isinstance(value, str) or not re.fullmatch(r'[0-9]+(?:/[0-9]+)*', value):
                    return
                targets.append(value)
        elif ref is not None:
            targets = [str(ref)]
        elif 'group_path' in args and 'image_index' in args:
            group, index = args['group_path'], args['image_index']
            if not isinstance(group, list) or isinstance(index, bool) or not isinstance(index, int):
                return
            if any(isinstance(v, bool) or not isinstance(v, int) for v in group):
                return
            matches = [p for p in panels if p.get('group_path') == group and p.get('image_index') == index]
            if len(matches) != 1:
                return
            targets = [matches[0]['panel_id']]
        else:
            # Unspecified row/column numbering conventions are not safe to guess.
            return
        allowed = {p['panel_id'] for p in requested}
        conflicts = []
        for target in targets:
            matches = [p for p in panels if p.get('panel_id') == target]
            if len(matches) != 1 or len(matches[0].get('letters', [])) != 1:
                return
            if target not in allowed:
                conflicts.append(matches[0])
        if conflicts:
            actual = ', '.join(str(p['letters'][0]) + ' (' + p['panel_id'] + ')' for p in conflicts)
            intended = ', '.join(name + ' (' + panel['panel_id'] + ')' for name, panel in zip(names, requested))
            raise ValueError('PANEL_ADDRESS_MISMATCH: you targeted ' + actual + '; the request names ' + intended + '. No edit was dispatched. Inspect current references and correct the target explicitly; nothing was retargeted or undone.')


    def validate_tool_call(self, tool_name, arguments, state, text):
        import re
        selection = state.get('selection') or {}
        panels = selection.get('selected_panels') or []
        explicit_target = re.search(r'\b(?:all|every|whole|entire)\b|\b(?:panel|letter)\s+(?:[a-z]|[0-9]+(?:/[0-9]+)?)\b', text, re.I)
        # "the third picture in the second row", "the top-left image" name a position, not a selection
        explicit_target = explicit_target or re.search(r'\b(?:first|second|third|fourth|fifth|sixth|seventh|eighth|last|\d+(?:st|nd|rd|th))\s+(?:picture|image|panel)\b|\b(?:top|bottom|upper|lower)[ -](?:left|right)\s+(?:picture|image|panel)\b', text, re.I)
        singular = re.search(r'\b(?:one|a|single|this|that|the)\s+(?:panel\s+)?(?:letter|label)\b', text, re.I)
        plural_style_collection=re.search(r'\b(?:the|these|those)\s+(?:panel\s+)?(?:letter|label)\s+(?:backgrounds|boxes|fills|fonts|sizes|colours|colors|positions|styles)\b',text,re.I)
        if plural_style_collection:singular=None
        operation = arguments.get('tool_name') if tool_name == 'use_pyfigures_tool' else tool_name
        if operation=='review_submission_readiness':self._quality_review_requested=True
        # "add a 10 um scale bar to images" / "to the panels" / "to the figure": plural
        # pictures with no letters after them mean every panel (it was refused)
        plural_target=re.search(r'\b(?:to|on|for|in)\s+(?:the\s+|my\s+|these\s+|those\s+)?(?:images|panels|pictures|photos|figure)\b(?!\s+(?:[a-z]|\d+/\d+)\b(?:\s*(?:,|and|&)|\s*$))',text,re.I)
        if operation=='set_scale_bar_all' and not plural_target and not re.search(r'\b(?:all|every|each|whole|entire|throughout)\b|\bscale[ -]?bars\b',text,re.I):
            # "Give a a scale bar", "put b a scale bar", "panel c": the request names its panel
            named=re.search(r'\b(?:panel|image)\s+([a-z]{1,2}|\d+/\d+)\b',text,re.I)
            if named and (re.search(r'\b(?:this|that|the|selected|current|same)\s*$',text[:named.start()],re.I)
                          or (named.group(1).lower() in ('a','an') and re.match(r'\s+(?:\d|scale|new|single|micro|µ)',text[named.end():],re.I))):
                # "the selected panel a 10 um scale bar", "this image a scale bar": an article, not panel a
                named=None
            named=named or re.search(r'\b(?:give|put|add|draw)\s+(?:panel\s+)?([a-z])\s+(?:a|an|one)\b',text,re.I)
            hint=(' The request names panel '+repr(named.group(1))+': call set_scale_bar with panel_ref='+repr(named.group(1))+' and the same length/pixel size; do not ask.') if named else ' Ask which image if the target is unclear.'
            raise ValueError('SCOPE_MISMATCH: A singular scale-bar request does not authorize changing every panel. Use set_scale_bar for the named or selected image.'+hint+' No bulk edit was submitted.')
        if operation in ('remove_group','delete_last_rows') and re.search(r'\b(?:picture|image|panel|photo)\b',text,re.I) \
                and not re.search(r'\b(?:rows?|groups?|lines?|columns?|pictures|images|panels|photos)\b',text,re.I):
            # "Delete the very last picture" once removed the whole last row
            raise ValueError('SCOPE_MISMATCH: The request names one picture, not a row. Remove only that panel with remove_image '
                             '(panel_ref = its letter; "the last picture" is the last letter in inspect_figure). Nothing was removed.')

        vague_annotation = re.search(r'\bannot\w*\b', text, re.I) and not re.search(
            r'\b(?:arrow\w*|roi\w*|rectangle|ellipse|circle|polygon|line|text|label|scale|remove|delete|clear)\b|["]', text, re.I)
        if vague_annotation and operation in ('add_annotation', 'add_roi_rect', 'add_roi_ellipse', 'add_roi_line', 'add_roi_polygon', 'add_arrow'):
            from ..errors import NeedsClarification
            named = re.search(r'\bpanel\s+([a-z]|[0-9]+(?:/[0-9]+)*)(?!\w)', text, re.I)
            target = 'panel ' + named[1] if named else 'this panel'
            raise NeedsClarification(f'What would you like to add to {target}?\n- Tell me the annotation you want for {target}\n- Open the annotation editor for {target}\nNo annotation was added.')
        read_only = operation and (operation.startswith(('inspect_', 'get_', 'list_', 'check_', 'describe_', 'audit_', 'explain_')) or operation in ('preview_figure', 'preview_panel', 'preview_luts', 'find_pyfigures_tools', 'readability'))
        args = arguments.get('arguments', {}) if tool_name == 'use_pyfigures_tool' else arguments
        # "How do I export the source data?" asks for steps; a local model ran export_source_data
        # or consolidate_figure instead. Teaching is not permission to edit or write files.
        how_to = re.match(r'\s*(?:how\s+(?:do|can|could|would|should)\s+(?:i|we|one)|can\s+i|could\s+i)\b', text, re.I) \
            and not re.search(r'\b(?:do it|for me|go ahead|then do|and do|please (?:do|apply|make|change|add|set))\b', text, re.I)
        if how_to and operation and operation.startswith(('export_', 'consolidate_', 'save_', 'render_', 'set_', 'add_', 'remove_', 'delete_', 'swap_',
                                                          'edit_', 'apply_', 'arrange_', 'restyle_', 'reorder_', 'move_', 'crop_', 'rotate_', 'split_', 'merge_')):
            raise ValueError('HOW_TO_NO_EDIT: the user asked HOW to do this, not to do it. Answer with the human GUI steps '
                             '(explain_how / explain_live_interaction), then offer to do it. Nothing was changed or written.')
        if operation in ('delete_last_rows', 'remove_group', 'remove_image', 'ungroup_all_images', 'remove_label_row') and not re.search(
                r'\b(?:delet\w*|remov\w*|drop|eras\w*|discard|get\s+rid|take\s+out|clear|cut|trim|lose|eliminat\w*|fewer|ungroup\w*|undo|keep\s+only|only\s+keep|just\s+keep)\b', text, re.I):
            # 'Put 0 pictures per row.' -> columns=0 refused, then delete_last_rows was accepted (24 -> 16 images)
            raise ValueError('REMOVAL_NOT_REQUESTED: the request does not ask to delete or remove anything. Never remove panels or rows as a '
                             'workaround for a refused or impossible edit; explain the problem and ask. Nothing was removed.')
        if not read_only and state.get('panel_references'):
            known = {str(p.get('panel_id', '')).casefold() for p in state['panel_references']}
            for p in state['panel_references']:
                known.update(str(v).casefold() for v in p.get('letters', []))
            stop = {'to', 'in', 'on', 'at', 'of', 'by', 'is', 'it', 'as', 'up', 'an', 'or', 'so', 'no', 'me', 'my', 'be', 'do', 'go', 'if', 'we', 'us'}
            for named in re.finditer(r'\b(?:image|panel|picture|photo|select|pick)\s+([a-z]{1,2}|\d+/\d+)(?![\w/])', text, re.I):
                ref = named[1].casefold()
                if ref not in known and ref not in stop:
                    # 'Select image aa, then make its letter blue.' once selected 0/0 and styled it
                    from ..errors import NeedsClarification
                    raise NeedsClarification(f'There is no panel {named[1]!r} in this figure. Which panel do you mean? '
                                             'Nothing was selected or changed.')
        if operation == 'swap_live_panels':
            spoken =re.search(r'\bswap\s+(?:panels?\s+|pictures?\s+|images?\s+)?([a-z]{1,2}|\d+/\d+)\s+(?:with|and)\s+(?:panel\s+)?([a-z]{1,2}|\d+/\d+)\b', text, re.I)
            if spoken:
                refs = {p['panel_id']: p['panel_id'] for p in state.get('panel_references', [])}
                for p in state.get('panel_references', []):
                    for letter in p.get('letters', []):refs[str(letter).lower()] = p['panel_id']
                canon = lambda r: refs.get(str(r).lower(), str(r).lower())
                if {canon(spoken[1]), canon(spoken[2])} != {canon(args.get('first')), canon(args.get('second'))}:
                    # "Swap aa with c": never swap a and c instead of saying aa does not exist
                    raise ValueError(f'SWAP_REFERENCE_MISMATCH: the request names {spoken[1]!r} and {spoken[2]!r}. Never substitute another panel; '
                                     'if a reference does not exist, tell the user and ask. Nothing was swapped.')
        self._named_panel_address_guard(operation, args, state, text)
        # Annotation tokens change after an earlier edit in this same turn.
        token_state = self.context() if operation == 'edit_annotation_properties' else state
        self._efficient_arguments(operation, args, token_state)
        if operation=='add_annotation' and args.get('panel_ref') is None and args.get('group_path') is not None and args.get('image_index') is not None:
            clause=re.split(r'\bthen\b|;',text,flags=re.I)[0]
            named=re.search(r'\b(?:write|add|put)\b.{0,160}?\b(?:on|to)\s+(?:(?:image|panel|picture)\s+)?([a-z])(?!\w)',clause,re.I)
            targets=[p for p in state.get('panel_references',[]) if named and named[1] in p.get('letters',[])]
            if len(targets)==1 and (args['group_path']!=targets[0]['group_path'] or args['image_index']!=targets[0]['image_index']):
                raise ValueError('PANEL_ADDRESS_MISMATCH: The requested note target is '+named[1]+'. Use panel_ref for that panel and omit guessed group_path/image_index. No annotation was added.')
        written=args.get('text') if operation in ('add_annotation','set_annotation_text') else None
        if isinstance(written,str) and written.strip() and written not in text and not re.search(r'\b(?:capital\w*|upper\s*case|lower\s*case|uppercase|lowercase|title\s*case|caps)\b',text,re.I):
            # The user's own words go in verbatim: the model may not recapitalise "sample" to "Sample".
            typed=[m[1] for m in re.finditer(r'(?:\b(?:write|type|put|add|say|saying|reads?|reading|text)\s+|["\'“‘])('+re.escape(written.strip())+r')(?!\w)',text,re.I)]
            if len(set(typed))==1:args['text']=written.replace(written.strip(),typed[0])
        match_text=args.get('match') if operation=='style_annotation' else args.get('substring') if operation=='edit_annotation_properties' else None
        every_match=re.search(r'\b(?:both|all|every\w*|each|wherever|containing|contains)\b',text,re.I)
        ordinal=every_match or re.search(r'\b(?:first|second|third|fourth|fifth|last|\d+(?:st|nd|rd|th)|occurrence|instance)\b',text,re.I)
        if isinstance(match_text,str) and match_text and not ordinal:
            references=state.get('panel_references',[])
            owner=next((p['panel_id'] for p in references if args.get('panel_ref') in [p['panel_id']]+p.get('letters',[]) or (args.get('group_path')==p.get('group_path') and args.get('image_index')==p.get('image_index'))),None)
            notes=(state.get('annotation_editor') or {}).get('editor_draft_objects',[]) if operation=='edit_annotation_properties' and state.get('annotation_editor') else state.get('text_annotations',[])
            index=args.get('text_index',args.get('annotation_index')) if operation=='style_annotation' else args.get('annotation_index')
            key='text_index' if operation=='style_annotation' else 'annotation_index'
            candidates=[a for a in notes if isinstance(a.get('text'),str) and (owner is None or a.get('panel_id',owner)==owner) and (index is None or a.get(key)==index)]
            # User decision 2026-10-25: a word of letters found once as a whole word is that one
            # ("treated" in "treated and untreated"); the tool applies the same rule.
            whole_once=len(match_text)>1 and match_text.replace(' ','').isalpha() and len(candidates)==1 and \
                len(re.findall(r'(?<!\w)'+re.escape(match_text)+r'(?!\w)',candidates[0]['text']))==1
            if len(candidates)==1 and candidates[0]['text'].count(match_text)>1 and not whole_once:
                from ..errors import NeedsClarification
                count=candidates[0]['text'].count(match_text)
                raise NeedsClarification(f'"{match_text}" matches {count} places in this annotation, including inside longer words. Which occurrence do you mean? No text was changed. Please choose; I will not guess an occurrence.')
        picked=args.get('occurrence') if operation in ('style_annotation','edit_annotation_properties') else None
        # occurrence="all" (every match, inside longer words too) needs words like
        # "everything containing"/"all"; a numbered occurrence needs an ordinal.
        if picked is not None and not (every_match if picked=='all' else ordinal):
            from ..errors import NeedsClarification
            word=args.get('match') or args.get('substring') or 'that text'
            raise NeedsClarification(f'"{word}" appears more than once in that text. Which one do you mean (the first, the second… or all of them)? No text was changed.')
        roi_edit=operation=='set_roi_properties' or (operation=='edit_annotation_properties' and bool(set(args.get('changes',{})) & {'stroke','fill_color','geometry','endpoints'}))
        if roi_edit and re.search(r'\b(?:the|that|this)\s+(?:box|rectangle)\b',text,re.I) and not re.search(r'\b(?:first|second|third|left|right|top|bottom|red|green|blue|yellow|white|black)\s+(?:box|rectangle)\b|\b(?:box|rectangle)\s+(?:on|at|to)\s+(?:the\s+)?(?:left|right|top|bottom)\b|\bannotation(?:_index| index)\s*[:=]?\s*\d',text,re.I):
            references=state.get('panel_references',[])
            target=next((p['panel_id'] for p in references if args.get('panel_ref') in [p['panel_id']]+p.get('letters',[]) or (args.get('group_path')==p.get('group_path') and args.get('image_index')==p.get('image_index'))),None)
            candidates=[a for a in state.get('roi_annotations',[]) if (target is None or a['panel_id']==target) and a['type'] in ('Rectangle2D','Rect2D','Square2D')]
            selected=[a for a in (state.get('annotation_editor') or {}).get('editor_draft_objects',[]) if a.get('selected') and a.get('type') in ('Rectangle2D','Rect2D','Square2D')]
            if len(candidates)>1 and len(selected)!=1:
                from ..errors import NeedsClarification
                raise NeedsClarification('Which rectangle do you mean? Several boxes match. Select one in the image editor or identify it by position or colour. No ROI was changed.')

        if operation=='set_lut' and isinstance(args.get('luts'),list):
            # After "blorple" was refused the model chose PURPLE itself: a colour table
            # must be one the user named.
            spoken=text.lower().replace('grey','gray')
            inverted_words=re.search(r'\b(?:invert\w*|inverse|revers\w*|negative)\b',spoken)
            def stem(name):
                # "reversed viridis" names MATPLOTLIB_viridis_r, "inverted gray" GRAY_INVERTED
                # (the first was refused, 2026-11-03)
                name=re.sub(r'^matplotlib_','',name.lower().replace('grey','gray'))
                if inverted_words:
                    name=re.sub(r'(?:_inverted|_r)$','',name)
                return re.sub(r'[^a-z ]','',name).strip().rstrip('s')   # Grays -> gray
            # a channel keeping its current table ("leave the other channels alone") needs no name
            ref=str(args.get('panel_ref') or '')
            current=next((p.get('luts') or [] for p in state.get('panel_references',[])
                          if ref and (p.get('panel_id')==ref or ref in [str(x) for x in p.get('letters',[])])),[])
            unnamed=[l for i,l in enumerate(args['luts']) if isinstance(l,str) and stem(l) and stem(l) not in spoken
                     and not (i<len(current) and isinstance(current[i],str) and stem(current[i])==stem(l))]
            if unnamed:
                from ..errors import NeedsClarification
                raise NeedsClarification('The request does not name the colour table '+', '.join(unnamed)+'. Which LUT do you want (e.g. GRAY, RED, GREEN, BLUE, MAGENTA, YELLOW_HOT; list_luts lists them all)? No LUT was changed.')
        greek=re.search(r'\b(?:panel|image|picture)\s+(alpha|beta|gamma|delta|epsilon|zeta|eta|theta|iota|kappa|lambda|mu|nu|xi|omicron|pi|rho|sigma|tau|upsilon|phi|chi|psi|omega)\b',text,re.I)
        if greek and not read_only and not any(greek[1].lower() in [str(x).lower() for x in p.get('letters',[])] for p in state.get('panel_references',[])):
            # "the letter from panel omega": no such panel, so nothing may be guessed.
            from ..errors import NeedsClarification
            raise NeedsClarification(f'There is no panel called {greek[1]} in this figure. Which panel do you mean? Nothing was changed.')
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
        # "exactly: X." or "Use this caption and italicize ...: X." both give the text verbatim
        exact=re.search(r'\bexactly\s*:\s*(.+?)\s*$',text,re.I|re.S) or re.search(r'\b(?:caption|l[ée]gende|legend)\b[^:\n]*:\s*(.+?)\s*$',text,re.I|re.S)
        if exact and operation=='set_figure_caption' and isinstance(args.get('caption'),str) and ' and ' not in exact[1] and ' then ' not in exact[1].lower():
            wanted=exact[1].strip().strip('"“”')
            if args['caption'].strip()!=wanted and args['caption'].strip().rstrip('.')==wanted.rstrip('.'):
                # "exactly: Cellules traitées." -> the model dropped the final period
                raise ValueError('CAPTION_NOT_EXACT: the request gives the exact caption '+repr(wanted)+', final punctuation included. Call set_figure_caption again with caption='+repr(wanted)+' (and the same final punctuation in caption_markdown). Nothing was changed.')
        corner=re.search(r'\b([a-z]+)\s+corners?\b',text,re.I)
        known_corner=r'top|bottom|upper|lower|left|right|centre|center|middle|same|other|opposite|each|every|all|any|one|that|this|which|its|their|the|a|different|another|nearest'
        if corner and not re.fullmatch(known_corner,corner[1],re.I) and (operation=='set_panel_letter_position' or (operation=='edit_panel_letters' and args.get('placement'))):
            # "the flarble corner" names no corner: never substitute one.
            from ..errors import NeedsClarification
            raise NeedsClarification('"'+corner[1]+' corner" is not a corner I know. Which corner do you want: top left, top right, bottom left or bottom right? Nothing was moved.')
        preserving_letters=re.search(r'\b(?:leave|keep|preserve)\b.{0,35}\b(?:panel\s+)?letters?\b.{0,20}\b(?:alone|unchanged|as (?:it|they) (?:is|are))\b',text,re.I)
        if preserving_letters and operation in ('style_annotation','set_annotation_text','add_annotation','set_roi_properties','edit_annotation_properties'):
            singular=None
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
        if re.search(r'\b(?:select|highlight|pick)\b',text,re.I):return None
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


    def preflight_manual_response(self, request):
        """Resolve a pure control-location question from reviewed help before model discovery."""
        import re
        if not re.match(r'^\s*where\s+(?:is|are)\b', request, re.I):
            return None
        # Mixed questions/actions must retain the normal conversational/tool path.
        if re.search(r'\b(?:and|then|also)\s+(?:please\s+)?(?:do|apply|flip|rotate|change|set|move|remove|delete|make|swap|open)\b', request, re.I):
            return None
        return self.finalize_manual_response(request)


    def finalize_manual_response(self,request):
        import re
        manual=bool(re.search(r'\b(?:how|explain|tutorial|instructions?|shortcuts?)\b|\bwhere\s+(?:is|are|do|can|should)\b|\bwhat\s+if\b',request,re.I))
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
        if guide.get('guide')=='export_pptx' and not re.search(r'powerpoint|pptx|\bppt\b|\bslides?\b',request,re.I):return None
        title=guide.get('title') or 'In PyFigures'
        content=title+':\n\n'+'\n'.join(str(i+1)+'. '+step for i,step in enumerate(steps))
        if guide.get('guide')=='reorder_panels':
            content+='\n\nWith automatic lettering enabled, letters follow panel positions.'
        return {'content':content,'evidence':{'kind':'authored_manual_guide','guide':guide,'operation_executed':False}}

    def _verify_letter_style_reply(self,request,reply,state):
        import re
        if not re.search(r'\bletters?\b',request,re.I):return None
        if re.search(r'\b(?:keep|leave|preserve)\b.{0,50}\bletters?\b.{0,20}\b(?:unchanged|alone)\b|\bwithout changing\b.{0,30}\bletters?\b',request,re.I):return None
        if not re.search(r'\b(?:done|success\w*|now|have been|has been|result)\b',reply,re.I):return None
        desired={}
        for prop,word in (('bold','bold'),('italic','italic'),('underline','underlin(?:e|ed)')):
            if re.search(r'\b'+word+r'\b',request,re.I):
                negative=re.search(r'\b(?:not|no longer|remove|disable|without)\s+(?:the\s+)?'+word+r'\b',request,re.I)
                desired[prop]=not bool(negative)
        if not desired:return None
        all_requested=bool(re.search(r'\b(?:all|every|throughout|entire)\b',request,re.I))
        selected={p['panel_id'] for p in (state.get('selection') or {}).get('selected_panels',[])}
        named=re.findall(r'\b(?:panel|letter)\s+([a-z])(?!\w)',request,re.I)
        if not all_requested and not selected and not named:return None
        try:
            current=self.request('letter_state')
            targets=[p for p in current.get('panels',[]) if all_requested or p['panel_id'] in selected or any(a.get('text','').casefold() in {x.casefold() for x in named} for a in p.get('letters',[]))]
            missing=[p['panel_id'] for p in targets if not p.get('letters') or any(any(bool(a.get(k))!=v for k,v in desired.items()) for a in p['letters'])]
            if not targets or missing:
                return {'content':'The requested panel-letter style was not verified in the figure. '+str(len(missing))+' of '+str(len(targets))+' targeted panels do not match '+str(desired)+'. I cannot confirm this edit. Other completed edits may remain.',
                        'evidence':{'status':'not_verified','requested':desired,'mismatched_panel_ids':missing,'target_count':len(targets)}}
        except Exception as exc:
            return {'content':'I could not verify the requested panel-letter style: '+str(exc)+'. The edit is not confirmed.',
                    'evidence':{'status':'unavailable','error':str(exc)}}
        return None

    def _verify_requested_selection(self,request,reply):
        import re
        match=re.search(r'\b(?:select|highlight|pick)\s+(?:the\s+)?(?:(?:panel|image|picture)\s+)?([a-z]|\d+(?:/\d+)+)(?!\w)',request,re.I)
        if not match or re.search(r"\b(?:do not|don't|never)\s+(?:select|highlight|pick)\b",request,re.I):return None
        if not re.search(r'\b(?:done|success\w*|now|changed|have been|has been|result)\b',reply,re.I):return None
        refs=[match[1]]
        tail=request[match.end():]
        if tail.startswith("'s"):return None
        next_word=re.match(r'\s+([A-Za-z]+)',tail)
        if next_word and next_word[1].lower() not in ('and','then','please','only','to','for','as','with'):return None
        while True:
            extra=re.match(r'^\s*(?:,|and)\s+([a-z]|\d+(?:/\d+)+)(?!\w)',tail,re.I)
            if not extra:break
            refs.append(extra[1]);tail=tail[extra.end():]
        try:
            current=self.request('inspect')
            selected=(current.get('selection') or {}).get('selected_panels',[])
            actual={str(p['panel_id']) for p in selected}
            actual.update(str(x) for p in selected for x in p.get('letters',[]))
            missing=[ref for ref in refs if ref not in actual]
            if missing:
                # The missing part is a pure GUI selection the user asked for
                # word for word (no document change): the host completes it
                # rather than reporting an unfinished request.
                try:
                    self.request('select_live_objects',{'panel_refs':refs})
                    current=self.request('inspect')
                    selected=(current.get('selection') or {}).get('selected_panels',[])
                    actual={str(p['panel_id']) for p in selected}
                    actual.update(str(x) for p in selected for x in p.get('letters',[]))
                    if all(ref in actual for ref in refs):
                        return {'content':reply.rstrip()+'\n\n'+', '.join(refs)+(' is' if len(refs)==1 else ' are')+' now selected in the figure, as requested.',
                                'evidence':{'status':'selection_completed_by_host','requested':refs,'selection':current.get('selection')}}
                except Exception:
                    pass
                return {'content':'The request is not fully complete: '+', '.join(missing)+' is not selected in the GUI. Other completed edits may remain.',
                        'evidence':{'status':'incomplete_selection','requested':refs,'missing':missing,'missing_operation':{'tool_name':'select_live_objects','arguments':{'panel_refs':refs}},'selection':current.get('selection')}}
        except Exception as exc:
            return {'content':'I could not verify the requested GUI selection: '+str(exc)+'. The full request is not confirmed.',
                    'evidence':{'status':'unavailable','error':str(exc)}}
        return None

    def _verify_requested_dialog(self,request,reply):
        import re
        if not re.search(r'\b(?:open|show)\b.*\b(?:properties|settings)\b',request,re.I):return None
        expected='Edit Inset' if re.search(r'\binset\b',request,re.I) else 'Edit ScaleBar' if re.search(r'\bscale[ -]?bar\b',request,re.I) else 'Edit text' if re.search(r'\b(?:text|label)\b',request,re.I) else None
        if expected is None:return None
        try:
            current=self.request('inspect')
            panel=re.search(r'\b(?:in|on)\s+(?:panel\s+)?([a-z])(?!\w)',request,re.I)
            wanted=next((p['panel_id'] for p in current.get('panel_references',[]) if panel and panel[1] in p.get('letters',[])),None)
            correct_owner=wanted is None or wanted==current.get('annotation_editor_panel_id')
            if expected not in current.get('native_dialogs',[]) or not correct_owner:
                return {'content':'The requested native properties are not open yet. Opening the panel editor alone did not complete this request.',
                        'evidence':{'status':'not_verified','expected_dialog':expected,'expected_panel_id':wanted,
                                    'actual_dialogs':current.get('native_dialogs',[]),'actual_panel_id':current.get('annotation_editor_panel_id')}}
        except Exception as exc:
            return {'content':'I could not verify the requested property dialog: '+str(exc),
                    'evidence':{'status':'unavailable','error':str(exc)}}
        return None

    def finalize_response(self,request,reply,state,preview=False):
        import re
        manual=self.finalize_manual_response(request)
        if manual:return manual
        if re.search(r'\b(?:how|tutorial|instructions|shortcut)\b',request,re.I):return None
        dialog_verification=self._verify_requested_dialog(request,reply)
        if dialog_verification:return dialog_verification
        selection_verification=self._verify_requested_selection(request,reply)
        if selection_verification:return selection_verification
        style_verification=self._verify_letter_style_reply(request,reply,state)
        if style_verification:return style_verification
        asks_ready=bool(re.search(r'\b(?:ready|readiness)\b',request,re.I) and
                        re.search(r'\b(?:is|are|whether|tell|check|review|submission|publication|submit)\b',request,re.I))
        asks_compliance=bool(re.search(r'\b(?:check|review|assess|audit)\b.*\b(?:compliance|print resolution|submission)\b',request,re.I))
        asks_publication=bool(re.search(r'\b(?:can|could|would|should)\b.*\b(?:submit|publish)\b',request,re.I))
        if not (asks_ready or asks_compliance or asks_publication or getattr(self,'_quality_review_requested',False)):return None
        try:
            evidence=self.request('submission_review',{})
        except Exception as exc:
            if str(exc).startswith('NO_TARGET'):
                return {'content':'Which journal and column (or which figure width) should I check it against? '
                                  'No target is known for this figure yet, and readiness depends on it.',
                        'evidence':{'status':'needs_target','error':str(exc)}}
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
    from qtpy_ai_sidecar import create_dock
    from .docking import dock_beside
    return dock_beside(window, create_dock(window, config, PyFiguresAdapter(descriptor)))
