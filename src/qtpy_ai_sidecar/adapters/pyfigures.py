"""Optional HTTP adapter to the existing isolated PyFigures prototype.

No PyFigures imports, source edits, monkey patches, or file-based figure editing.
The existing bridge marshals requests onto the application's Qt thread.
"""
import json
from pathlib import Path
import uuid
import urllib.request


class PyFiguresAdapter:

    def __init__(self, descriptor):
        self.descriptor = Path(descriptor)

    def request(self, operation, arguments=None):
        connection = json.loads(self.descriptor.read_text())
        from urllib.parse import urlsplit
        url = urlsplit(connection['url'])
        if url.hostname not in ('127.0.0.1', 'localhost', '::1'):
            raise ValueError('The PyFigures bridge must be local')
        payload={'operation':operation,'arguments':arguments or {},'request_id':str(uuid.uuid4())}
        if operation in ('inspect_annotation_objects','letter_state','select_live_objects','open_annotation_editor'):
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
            elif status in ('applied', 'interrupted'):
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
              'search_images',
              # plain reads: 9 get_image_property re-reads counted as edits, so the
              # engine could not tell checking from editing (2026-11-12)
              'get_image_property','list_image_properties','get_scale_bar','get_journal_style',
              'list_colors','list_luts','list_images','list_insets','list_label_rows',
              'list_journal_presets','list_journal_styles','describe_figure','preview_figure'}
        if tool_name=='use_pyfigures_tool':
            return arguments.get('tool_name') in pure
        if tool_name in pure:return True
        if tool_name in ('select_live_objects','undo_redo','show_me_how','close_guidance',
                         'open_annotation_editor','open_annotation_properties',
                         'open_native_menu','use_native_gui','native_gui_keys',
                         'native_gui_gesture','native_gui_drop_files'):
            return False
        return None  # Other connected services need their own explicit MCP hint.


    # -- procedures (qtpy_ai_sidecar.procedures): what a replayed chat keeps -------------
    _PROCEDURE_SKIP = {'select_live_objects', 'open_annotation_editor', 'open_annotation_properties',
                       'show_me_where', 'show_me_how', 'close_guidance', 'open_native_menu', 'use_native_gui',
                       'native_gui_keys', 'native_gui_gesture', 'native_gui_drop_files',
                       # the procedure tools themselves: a procedure does not save procedures
                       'save_chat_procedure', 'run_procedure', 'run_procedure_here', 'list_chat_steps'}

    def procedure_role(self, tool_name, arguments):
        """edit / read / undo / redo / skip for a call of a replayed chat."""
        op, args = (arguments.get('tool_name', ''), arguments.get('arguments') or {}) \
            if tool_name == 'use_pyfigures_tool' else (tool_name, arguments or {})
        if isinstance(args, str):     # a model sent the inner arguments as JSON text (Qwen3.5-9B, 2026-11-14)
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        if not isinstance(args, dict):
            args = {}
        op = str(op or '')
        if op == 'undo_redo':
            return 'redo' if str(args.get('action', 'undo')) == 'redo' else 'undo'
        if op in self._PROCEDURE_SKIP:
            return 'skip'
        if op.startswith(('get_', 'list_', 'inspect_', 'describe_', 'check_', 'preview_', 'explain_', 'find_',
                          'audit_', 'search_', 'review_')) or args.get('dry_run') \
                or self.is_read_only_call('use_pyfigures_tool', {'tool_name': op}) is True:
            return 'read'
        return 'edit'

    @staticmethod
    def make_demo_video(dock, chat=None):
        """Procedures > Make a demo video from a chat…: PyFigures' dialog
        (pyfigures.gui.chat_video_dialog); the video is filmed off-screen by
        pyfigures.assistant.chat_video, without the model."""
        from pyfigures.gui.chat_video_dialog import open_dialog
        return open_dialog(dock.window(), chat)

    @staticmethod
    def open_mcp_setup(dock):
        """Model > Another AI app: PyFigures' MCP server window (register it with Claude, LM
        Studio, Codex... in one click, or start its HTTP server)."""
        window = dock.window()
        if hasattr(window, 'open_mcp_server_dialog'):
            return window.open_mcp_server_dialog()
        from pyfigures.gui.mcp_server_dialog import McpServerDialog
        return McpServerDialog(window).exec_()

    @staticmethod
    def describe_call(tool_name, arguments):
        if tool_name != 'use_pyfigures_tool':
            return tool_name + ' ' + json.dumps(arguments, ensure_ascii=False)
        shown = {k: v for k, v in (arguments.get('arguments') or {}).items() if k != 'pyf_path'}
        text = str(arguments.get('tool_name', '')) + ' ' + json.dumps(shown, ensure_ascii=False)
        batch = arguments.get('batch')
        return text + (f' × {len(batch)}' if batch else '')

    def context(self):
        result = self.request('inspect')
        summary = result.get('figure_summary') or {}
        if summary.get('empty'):     # a short state lets the model answer without any tool step
            return {'figure_summary': summary, 'native_gui_available': result.get('native_gui_available'),
                    'revision': result.get('revision'), 'dirty': result.get('dirty')}
        context = {key: result.get(key) for key in ('figure_summary', 'document', 'selection', 'verified_letter_specification', 'panel_references', 'text_annotations', 'roi_annotations', 'insets', 'last_canvas_click', 'annotation_editor_status', 'native_gui_jobs', 'native_gui_available', 'revision', 'dirty')}
        if result.get('annotation_editor_open'):
            context['annotation_editor']=self.request('inspect_annotation_objects')
        return context

    current_request = ('', '')

    def request_rules(self):
        """The application's rules for the topics this request's words call for (scale
        bars, ROIs, letters...), sent with it: only those, so the first message stays
        small, and before the model's first step, so it needs no search to learn them
        (2026-11-19: Mistral previewed a panel seven times for "draw ROIs over every
        cell" without ever being told detect_objects does it in one call)."""
        text, earlier = self.current_request
        if not str(text).strip():
            return ''
        try:
            return str(self.request('request_rules', {'text': text, 'earlier': earlier}).get('rules') or '')
        except Exception:                # an older PyFigures: no such operation
            return ''

    def context_instructions(self, state):
        rules = self.request_rules()
        text = self._context_instructions(state)
        return text + (' RULES FOR THIS REQUEST (follow them; no search needed to learn them): ' + rules if rules else '')

    def _context_instructions(self, state):
        selection = state.get('selection') or {}
        if (state.get('figure_summary') or {}).get('empty'):
            return ('The figure is empty. For questions about it, reply at once from figure_summary (answer and how_to_add_content), '
                    'without tools. For a request to add content, discover the tool with find_pyfigures_tools.')
        return ('This state is current: answer "what is in the figure?" from figure_summary and panel_references without calling inspect_figure again; '
                + ('preview_figure only when asked how it looks. ' if not getattr(self, 'vision', False) else 'preview_figure only when the look itself is the question ("how does it look", a layout or colours '
                     'you chose); never just to confirm an edit whose result was read back: answer at once '
                     '(each preview costs the user a model round trip, 5-20 s). ') +
                'When annotation_editor is present, editor_draft_objects and selected=true describe the live editor selection. Edits there affect its draft until native OK; preserve Cancel. Use edit_annotation_properties with the CURRENT editor_draft_objects token, or inspected native controls. Main-object tokens describe the unchanged figure, not the draft. After each edit use its returned next_token; never reuse the pre-edit token or silently close the dialog. '
                'If a capability is missing from dedicated MCP tools, discover inspect_native_gui and inspect the actual native controls instead of concluding the GUI cannot do it. Use_native_gui takes only inspected IDs and exact choices. Native context/drag menus are available via open_native_menu; keyboard, canvas gestures and file drops have native_gui tools. Prefer dedicated semantic tools for common edits. '
                'Native GUI calls return queued jobs, not success. Inspect native_gui jobs and active modal controls, fill native fields and accept/cancel as requested, then verify actual document state. Do not claim queued or running work has completed. Teaching requests still do not authorize using edit controls. '
                'How-to/manual/shortcut questions are teaching requests, not permission to edit. For native arrow keys and drag/drop discover explain_live_interaction; include figure focus, selection level, source/target and relevant verified shortcuts. For other topics use authored explain_how/show_me_how. Never invent modifiers or menu labels. Never provide Python unless code or recipe was explicitly requested. '
                'For arrange_live_images, columns is the number of images per row; a row count is a different request; uneven rows (e.g. 3-2-2-2) are row_counts=[3, 2, 2, 2] in one call.For set_figure_caption, caption is exact plain text including punctuation, title is separate, and caption_markdown is an optional formatted STRING, never a boolean. Use set_scale_bar with panel_ref for a single panel; set_scale_bar_all is only for a whole-figure request. A scale bar asked for without a length: call set_scale_bar without bar_width_in_units (a round length of about 15 % of the width is chosen, in px when the image has no pixel size, and the reply says so); never ask for the length first. The user has the final word: a length, unit or label they give is used exactly, even a tiny bar; a size warning is information for them, not a reason to change it. "Image dimensions" / dims / shape: give each panel\'s dimensions.text from panel_references (the numpy axes and shape, e.g. tzyxc 19 × 21 × 300 × 400 × 2), not only width × height. '
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
                'Whenever you list choices for a change (always for a HELP request such as "help me change the channel colours of e"), add one more choice: "show me where to click". On that choice call show_me_where with EVERY route that does it (menu bar; right-click menu of the object at level image or row; or the panel editor tab and buttons, e.g. editor_tab="File Infos + Scale", controls=["Reset all LUTs"]): all are outlined at once and cleared when it worked. Say what the yellow selection outline surrounds and what to click first. open_menus=true only when the user explicitly asks to be shown the menu; never click for them in that mode. '
                'panel_references.channel_colours is what each channel shows now (its LUT, else the file\'s own colour): "swap channels 1 and 2" = set_lut with those colours permuted, e.g. [RED, GREEN, BLUE] -> luts=["GREEN", "RED", "BLUE"]. '
                'Channels cannot be reordered, but each channel colour can be set on its own (set_lut; GUI: right-click > Appearance > Set LUT(s), or the editor File Infos + Scale tab > Set LUTs): say so and offer both, with an example such as "make channel 1 blue, channel 2 red". '
                'GUI how-to answers end with "Should I highlight where to click, or open it for me?". "highlight where to click" (or show me where) = show_me_where with every route of your previous answer. "open it for me" = the same show_me_where call with open_menus=true: it opens the menus down to the entry the user clicks, or (where=editor, panel_ref, editor_tab) the panel editor with its buttons outlined; never perform the edit itself. '
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
                # bold/italic/underline are fields of edit_panel_letters since 2026-11-12 ("the letter
                # bold on every rotated panel": restyle_texts bolded all nine)
                unsupported = {'opacity'} & set(args)
                if unsupported:
                    raise ValueError('Unsupported edit_panel_letters fields: ' + ', '.join(sorted(unsupported)) + '. Opacity requires a supported discovered tool. No edit submitted; fields that would change state were not silently discarded.')



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
        # "add bars to a d e, remove the letter of b, and make h green": other lone letters
        # name panels too, so the verb pattern did not find the complete target set.
        others = re.findall(r"(?<![\w'’./-])[b-hj-z](?![\w'’./-])", source.lower())
        if any(letter not in names for letter in others):
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


    _SELF_EDIT_OK = frozenset({'open_annotation_editor', 'open_annotation_properties', 'show_me_where', 'select_live_objects',
                               'explain_how', 'explain_live_interaction', 'undo_redo'})

    _NUMBER_WORDS = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8,
                     'nine': 9, 'ten': 10, 'eleven': 11, 'twelve': 12, 'fifteen': 15, 'twenty': 20}

    @staticmethod
    def _accepts_offered_removal(text, state):
        """The last answer offered to remove panels ("tell me which one you want and I'll keep
        only that plot and remove the other three") and the user picks: "I'll go for the box
        plot finally" was refused twice, then asked to confirm (user chat 2026-11-18)."""
        import re
        offer = str((state or {}).get('_last_reply') or '')
        if not re.search(r"\b(?:remov\w*|delet\w*|keep\s+only|only\s+keep|drop)\b[^.?!\n]*", offer, re.I):
            return False
        if not re.search(r"\b(?:which|pick|choose|tell\s+me|confirm|say)\b", offer, re.I):
            return False                     # a removal it did not offer as a choice
        # "no", "keep them all", "don't remove": not an acceptance
        return not re.search(r"\b(?:no|nope|don['’]?t|do\s+not|never|keep\s+(?:them|all|both|every\w*)|none)\b", text, re.I)

    @classmethod
    def _over_asked_count(cls, text, state):
        """"build a figure from 10 random images": the model added 11, the guard refused
        to remove its own extra panel and it ended asking the user (2026-11-16). A
        removal that brings the figure toward the number asked for is allowed."""
        import re
        m = re.search(r'\b(\d{1,3}|' + '|'.join(cls._NUMBER_WORDS) + r')\b(?:\s+\w+){0,3}?\s+'
                      r'(?:images?|panels?|pictures?|photos?|files?|micrographs?)\b', text, re.I)
        if not m:
            return False
        asked = int(m[1]) if m[1].isdigit() else cls._NUMBER_WORDS[m[1].lower()]
        panels = (state or {}).get('panel_references') or []
        return len(panels) > asked

    @staticmethod
    def _wants_to_edit_himself(text):
        """"I want to edit / move / adjust X" with no value to set ("to red", "by 10 px",
        "make it…"), or "myself", "by hand", "so I can": the user edits, the chat opens."""
        import re
        # "have me edit the position manually" (user chat 2026-11-13)
        if re.search(r"\b(?:my\s*self|by\s+hand|manually|so\s+(?:that\s+)?i\s+can\s+(?:edit|do|move|change|adjust|fix|tweak)|"
                     r"(?:let|have|allow)\s+me\s+(?:to\s+)?(?:edit|do|move|change|adjust|fix|tweak|correct))\b", text, re.I):
            return True
        wish = re.search(r"\b(?:i|i'd|i'll)\s+(?:wanna|want\s+to|would\s+like\s+to|like\s+to|need\s+to|will|have\s+to)\s+"
                         r"(?:edit|adjust|tweak|reposition|fine[ -]?tune)\b", text, re.I)
        if not wish:
            return False
        rest = text[wish.end():]
        return not re.search(r"\b(?:to|into|by|with)\s+\S|\b(?:make|set|put|turn|use|change|move|add|remove|delete)\b|\d", rest, re.I)

    def validate_tool_call(self, tool_name, arguments, state, text):
        """Each item of a batch (one call, many items) passes the same guards as a
        single call would: the shared arguments merged with that item."""
        batch = arguments.get('batch') if tool_name == 'use_pyfigures_tool' else None
        if not batch or not isinstance(batch, list):
            return self._validate_one(tool_name, arguments, state, text)
        base = arguments.get('arguments') or {}
        for item in batch:
            merged = {**base, **item} if isinstance(item, dict) else base
            self._validate_one(tool_name, {**arguments, 'arguments': merged, 'batch': None}, state, text)

    def _validate_one(self, tool_name, arguments, state, text):
        import re
        selection = state.get('selection') or {}
        panels = selection.get('selected_panels') or []
        explicit_target = re.search(r'\b(?:all|every|whole|entire)\b|\b(?:panel|letter)\s+(?:[a-z]|[0-9]+(?:/[0-9]+)?)\b', text, re.I)
        # "#3", "number 3": the numbers the canvas shows on selected panels (2026-11-12)
        explicit_target = explicit_target or re.search(r'#\s?\d+\b|\b(?:number|no\.?|n°)\s?\d+\b', text, re.I)
        # "the third picture in the second row", "the top-left image" name a position, not a selection
        explicit_target = explicit_target or re.search(r'\b(?:first|second|third|fourth|fifth|sixth|seventh|eighth|last|\d+(?:st|nd|rd|th))\s+(?:picture|image|panel)\b|\b(?:top|bottom|upper|lower)[ -](?:left|right)\s+(?:picture|image|panel)\b', text, re.I)
        # "make g bigger" → "the letter", "add a label to b": a lone letter names the panel
        # (Mistral Large 4, 2026-11-10: both were refused as "which panel?").
        explicit_target = explicit_target or re.search(r"(?<![\w'’./-])[b-hj-z](?![\w'’./-])|\b(?:to|of|in|on|from|for)\s+[ai]\s*(?:$|[.,;!?\n]|\s(?:to|into|by|with|as|and|or|is|too|should|please|bigger|smaller|larger)\b)", text, re.I)
        singular = re.search(r'\b(?:one|a|single|this|that|the)\s+(?:panel\s+)?(?:letter|label)\b', text, re.I)
        plural_style_collection=re.search(r'\b(?:the|these|those)\s+(?:panel\s+)?(?:letter|label)\s+(?:backgrounds|boxes|fills|fonts|sizes|colours|colors|positions|styles)\b',text,re.I)
        if plural_style_collection:singular=None
        operation = arguments.get('tool_name') if tool_name == 'use_pyfigures_tool' else tool_name
        if operation=='review_submission_readiness':self._quality_review_requested=True
        if operation in self._GUIDING_TOOLS:self._guided=True
        # "add a 10 um scale bar to images" / "to the panels" / "to the figure": plural
        # pictures with no letters after them mean every panel (it was refused)
        plural_target=re.search(r'\b(?:to|on|for|in)\s+(?:the\s+|my\s+|these\s+|those\s+)?(?:images|panels|pictures|photos|figure)\b(?!\s+(?:[a-z]|\d+/\d+)\b(?:\s*(?:,|and|&)|\s*$))',text,re.I)
        if operation=='set_scale_bar_all' and not plural_target and not re.search(r'\b(?:all|every|each|whole|entire|throughout|everywhere|everything|partout|toutes?|tous|chaque)\b|\b(?:scale[ -]?)?bars\b|\bbarres\b',text,re.I):
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
        if operation == 'preview_panel':
            self._panel_previewed_for = text
        if operation == 'transform_image' and self._crop_needs_a_look(args, text) and getattr(self, '_panel_previewed_for', None) != text:
            # "crop #5 so that the burnt in scale bar gets hidden": the model looked at the
            # whole figure, then cut 320 px blind (user chat 2026-11-13)
            ref = args.get('panel_ref') or '<the panel>'
            raise ValueError(f'CROP_NEEDS_PANEL_PREVIEW: the crop values must come from the panel\'s own pixels. Call '
                             f'preview_panel(panel_ref="{ref}") first: it shows that panel\'s whole source image with '
                             f'pixel rulers and its current crop. Read the region\'s edges off the rulers, then crop once. '
                             f'Nothing was changed.')
        # the panels this request has added ROIs to: removing them again is cleaning up its own
        # work (replay 2026-11-20: detect_objects added 84 specks, remove_rois was refused, and
        # the model deleted them one call at a time until the steps ran out)
        if getattr(self, '_rois_added', (None, set()))[0] != text:
            self._rois_added = (text, set())
        if operation in ('detect_objects', 'add_roi_rect', 'add_roi_ellipse', 'add_roi_polygon', 'add_roi_line') \
                and args.get('panel_ref'):
            self._rois_added[1].add(str(args['panel_ref']).lower())
        own_rois = str(args.get('panel_ref') or '').lower() in self._rois_added[1]
        if operation == 'remove_rois' and not own_rois and not re.search(
                r'\b(?:remov\w*|delet\w*|clear\w*|eras\w*|get\s+rid|replac\w*|instead|rather|prefer\w*|swap\w*|'
                r'turn\w*\s+(?:them|the\s+\w+)\s+into|change\w*|convert\w*|start\s+(?:over|again)|redo|undo)\b', text, re.I):
            # bulk removal only for words that ask to remove or replace the ROIs
            raise ValueError('REMOVAL_NOT_REQUESTED: remove_rois deletes every ROI of the panel; the request does '
                             'not ask to remove or replace ROIs. Nothing was removed. To take back only some ROIs, '
                             'remove_annotation with batch=[{"annotation_index": ...}, ...] in ONE call.')
        if (operation in ('add_roi_rect', 'add_roi_ellipse', 'add_roi_polygon', 'add_arrow')
                and re.search(r'\b(?:cells?|nucle(?:us|i)|embryos?|objects?|blobs?|spots?|particles?|beads?)\b', text, re.I)
                and getattr(self, '_panel_previewed_for', None) != text):
            # "draw ROIs over every cell in e": two boxes placed by eye from the whole figure,
            # both off target (user chat 2026-11-13)
            ref = args.get('panel_ref') or '<the panel>'
            raise ValueError(f'LOOK_AT_THE_PANEL_FIRST: ROIs on objects must come from the panel\'s own pixels. For '
                             f'every / each object call detect_objects(panel_ref="{ref}") once (it boxes them all); for '
                             f'a few named ones call preview_panel(panel_ref="{ref}") and read their coordinates off '
                             f'its rulers (region=[x0, y0, x1, y1] zooms). Nothing was changed.')
        if operation == 'open_annotation_editor' and args.get('panel_ref'):
            # the model opened it: "I made a mistake" / "open it again" next reopens it
            self._last_editor = (str(args['panel_ref']), args.get('tab') if args.get('tab') in
                                 ('annotations', 'crop', 'rotate', 'scale', 'text') else 'annotations')
            self._turns_since_editor = 0
        if operation and not read_only and args.get('panel_ref') and operation != 'open_annotation_editor':
            # "have me edit it manually" next means THIS panel and this kind of edit (user chat
            # 2026-11-23: after the chat cropped a, it opened the editor of the selected panel b)
            self._last_edit = (str(args['panel_ref']), self._editor_tab_for(operation, args))
            self._turns_since_edit = 0
        from qtpy_ai_sidecar.quoting import quotes_reply     # absolute: the adapter is also loaded on its own
        if operation and not read_only and operation not in self._SELF_EDIT_OK and self._wants_to_edit_himself(text) \
                and not quotes_reply(text, (state or {}).get('_last_reply', '')):     # a pasted option: its "manually" is ours
            # "i wanna edit smallest ROI inset in b" made a second inset (user chat 2026-11-12)
            raise ValueError('SELF_EDIT: the user wants to make this edit by hand, not have it made. Open the editor for '
                             'them: open_annotation_editor(panel_ref=<the panel>) (or show_me_where), then let them work. '
                             'Nothing was changed.')
        if operation in ('delete_last_rows', 'remove_group', 'remove_image', 'ungroup_all_images', 'remove_label_row') and not re.search(
                r'\b(?:delet\w*|remov\w*|drop|eras\w*|discard|get\s+rid|take\s+out|clear|cut|trim|lose|eliminat\w*|fewer|ungroup\w*|undo|keep\s+only|only\s+keep|just\s+keep)\b', text, re.I) \
                and not (operation == 'remove_image' and self._over_asked_count(text, state)) \
                and not self._accepts_offered_removal(text, state):
            # 'Put 0 pictures per row.' -> columns=0 refused, then delete_last_rows was accepted (24 -> 16 images)
            raise ValueError('REMOVAL_NOT_REQUESTED: the request does not ask to delete or remove anything. Never remove panels or rows as a '
                             'workaround for a refused or impossible edit; explain the problem and ask. Nothing was removed.')
        if not read_only and state.get('panel_references'):
            known = {str(p.get('panel_id', '')).casefold() for p in state['panel_references']}
            for p in state['panel_references']:
                known.update(str(v).casefold() for v in p.get('letters', []))
            stop = {'to', 'in', 'on', 'at', 'of', 'by', 'is', 'it', 'as', 'up', 'an', 'or', 'so', 'no', 'me', 'my', 'be', 'do', 'go', 'if', 'we', 'us',
                    # 'give each image bg a different bg color' (2026-11-12): abbreviations, not panels
                    'bg', 'fg', 'px', 'pt', 'mm', 'cm', 'um', 'nm', 'ok', 'id', 'ch', 'sz'}
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
        # "make it fit one column of nature": a page width; the nine panels were stacked in one
        # column first (Mistral Large 4, 2026-11-12)
        if operation == 'arrange_live_images' \
                and re.search(r'\b(?:nature|science|cell|plos|elife|pnas|embo|jcb|neuron|development|current biology|journal)\b', text, re.I) \
                and re.search(r'\b(?:one|single|1|two|double|2|1\.5|full)[- ]?(?:columns?|width)\b|\bcolumns?\s+(?:of|width|in|for)\b', text, re.I) \
                and not re.search(r'\b(?:stack\w*|arrange\w*|rearrange\w*|layout|per row|vertical\w*|rows?)\b', text, re.I):
            raise ValueError('JOURNAL_COLUMN: a column of a journal is a page WIDTH, not a layout. Keep the panels where they are and '
                             'use resize_figure(journal=..., column="single" or "double"). Nothing was rearranged.')
        # "make it publication ready": the figure was resized to 89 mm and every letter turned
        # white without a word; "make it nicer" had been asked back correctly
        last_line = (text.strip().splitlines() or [''])[-1]
        checks_only = ('check_', 'inspect_', 'get_', 'list_', 'review_', 'preview_', 'render_', 'find_', 'journal_info',
                       'validate_', 'describe_', 'show_me', 'select_live', 'generate_alt')
        if re.search(r'\b(?:publication|submission|print)[- ]ready\b|\bready\s+(?:for|to)\s+(?:publication|submission|submit|publish|print)\b',
                     last_line, re.I) \
                and not re.search(r'\b(?:nature|science|cell|plos|elife|pnas|embo|jcb|neuron)\b|\d\s*(?:mm|cm|dpi|pt)\b', last_line, re.I) \
                and not str(operation or '').startswith(checks_only):
            raise ValueError('VAGUE_REQUEST: "publication ready" names no change. Run read-only checks only (review_submission_readiness '
                             'with width_mm=89 if no journal is known, check_resolution, check_scale_consistency), report what fails in '
                             'plain words, and ask which fixes to apply and for which journal. Nothing was changed.')
        # Annotation tokens change after an earlier edit in this same turn.
        token_state = self.context() if operation == 'edit_annotation_properties' else state
        if operation == 'edit_panel_letters':
            self._quote_the_request(args, text)
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
            # "use the default matplotlib lut" (2026-11-16): a library's default colour table
            # is named by naming the library; it is not "default colours" (the file's own):
            # MATPLOTLIB_viridis was refused three times and the turn ended
            library_default=None
            for library,lut in ((r'matplot ?lib|mpl|pyplot|python',' viridis'),(r'fiji|image ?j',' gray')):
                if re.search(rf'\bdefault\b[^.?!]{{0,15}}\b(?:{library})\b|\b(?:{library})(?:\'s)?\b[^.?!]{{0,15}}\bdefault\b',spoken):
                    library_default=lut
                    spoken+=lut
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
            panel_state=next((p for p in state.get('panel_references',[])
                              if ref and (p.get('panel_id')==ref or ref in [str(x) for x in p.get('letters',[])])),{})
            # what each channel shows now: its LUT, else the image file's own colour
            shown=panel_state.get('channel_colours') or []
            current=[l or (shown[i] if i<len(shown) else None) for i,l in enumerate(panel_state.get('luts') or [None]*len(shown))]
            # "swap channel 1 and 2" (2026-11-05): GREEN, RED was refused as unnamed; a swap
            # moves the colours the channels already show, so those names need no repeating
            swapping=re.search(r'\b(?:swap\w*|exchang\w*|switch\w*|permut\w*|reorder\w*|invert\w* (?:the )?order|revers\w* (?:the )?order)\b',spoken) \
                and re.search(r'\b(?:channels?|chanels?|colou?rs?|luts?)\b',spoken)
            shown_names={stem(c) for c in current if isinstance(c,str)}
            # "remove all LUTs" (2026-11-05): GRAY was refused as unnamed and the turn ended;
            # removing / resetting a LUT means the image file's own LUT: set_lut's NONE
            # (DEFAULT is accepted as a synonym)
            removing=re.search(r'\b(?:remov\w*|reset\w*|clear\w*|undo|delete\w*|drop|strip|get rid of|no|without|original|acquisition)\b'
                               r'[^.?!]{0,40}?\b(?:luts?|colou?r ?(?:tables?|maps?)|look-?up tables?|pseudo-?colou?rs?)\b',spoken) \
                or re.search(r'\b(?:luts?|colou?r ?tables?)\b[^.?!]{0,30}?\b(?:off|removed|gone|reset)\b',spoken) \
                or re.search(r'\b(?:default|restor\w*|original|natural|normal|own|real|true)\b[^.?!]{0,30}?\b(?:luts?|colou?rs?|channels?)\b'
                             r'|\b(?:luts?|colou?rs?)\b[^.?!]{0,30}?\b(?:unnatural|weird|strange|odd|wrong|off|fake|garish|ugly)\b',spoken)
            if library_default and not re.search(r'\b(?:remov\w*|reset\w*|clear\w*|delete\w*|get rid of|without|original|natural|normal|own)\b',spoken):
                removing=None             # "default" named the library's map, not the file's colours
            # "the colors look unnatural can this be fixed" (2026-11-12): going back to the image
            # file's own colours (NONE) is the expected fix, and what the refusal offers
            offered_default=re.search(r"image's own colours",str(state.get('_last_reply') or ''))
            # "default LUTs" on a 2-3 channel image also means red, green, blue for many people
            # (user, 2026-11-16): the plain RGB order is accepted, as is the file's own (NONE)
            plain_rgb=bool(removing) and 2<=len(args['luts'])<=3 and [stem(l) if isinstance(l,str) else None
                                                                    for l in args['luts']]==['red','green','blue'][:len(args['luts'])]
            # ... and when the file's own colours are not those, "default" alone could be either: ask
            own_colours=[stem(c) if isinstance(c,str) else None for c in shown]
            if (removing and 2<=len(args['luts'])<=3 and len(own_colours)==len(args['luts'])
                    and own_colours!=['red','green','blue'][:len(own_colours)]
                    and re.search(r'\bdefault\b',spoken)
                    and not re.search(r'\b(?:original|own|file|acquisition|natural|normal|remov\w*|reset\w*|clear\w*|'
                                      r'delete\w*|get rid of|without|red|green|blue|rgb)\b',spoken)
                    and all(isinstance(l,str) and stem(l) in ('none','default','red','green','blue') for l in args['luts'])):
                from ..errors import NeedsClarification
                # bold options: the chat makes them clickable, and either answer passes this guard
                raise NeedsClarification('No LUT was changed. By "default" LUTs, do you mean **the image\'s own colours ('
                                         + ', '.join(str(c).upper() for c in shown) + ')** or **red, green, blue**?')
            unnamed=[l for i,l in enumerate(args['luts']) if isinstance(l,str) and stem(l) and stem(l) not in spoken
                     and not (removing and stem(l) in ('default','none'))
                     and not plain_rgb
                     and not (swapping and stem(l) in shown_names)
                     and not (i<len(current) and isinstance(current[i],str) and stem(current[i])==stem(l))]
            # "try GRAY" (2026-11-05): after a one-LUT warning the model put GRAY on every
            # channel of 2- and 3-channel images; same-coloured channels add up and cannot be
            # told apart, so that needs the user's own words
            names=[stem(l) for l in args['luts'] if isinstance(l,str) and stem(l) and stem(l) not in ('none','default')]
            repeated=sorted({n for n in names if names.count(n)>1})
            if repeated and not re.search(r'\b(?:all|every|each|both|the)\s+(?:\w+\s+)?channels?\b|\bchannels?\s+(?:all|both)\b|\bper channel\b'
                                          # "make everything grayscale": one grey image is what was asked (2026-11-12)
                                          r'|\bgr[ae]y ?scale\b|\bblack (?:and|&) white\b|\bmonochrome\b|\bnoir et blanc\b|\bniveaux de gris\b',spoken):
                from ..errors import NeedsClarification
                raise NeedsClarification(f'This would give the {", ".join(n.upper() for n in repeated)} LUT to {names.count(repeated[0])} channels of the same image: '
                                         'they would add up in one colour and could no longer be told apart. Do you want that, or one channel '
                                         'in gray (the others hidden), or a channel split? No LUT was changed.')
            if unnamed and removing:
                raise ValueError('Removing a LUT, or colours back to normal, means going back to the LUT of the image '
                                 'file itself (its own colours): use "NONE" for each channel, e.g. luts=["NONE", "NONE"], '
                                 'unless the user asked for '
                                 + ', '.join(unnamed) + '. No LUT was changed.')
            # "is it colour blind safe?" -> the assistant proposes magenta/green -> "fix it" (2026-11-12):
            # colours the assistant offered and the user accepted, or a choice left to the assistant
            offered=str(state.get('_last_reply') or '').lower()
            accepting=re.search(r"\b(?:yes|yep|yeah|ok|okay|sure|please|do it|do that|go ahead|go for it|fix it|fix them|fix that|apply|sounds good|"
                                r"first|second|third|option|that one|the same|oui|vas[- ]y|d'accord)\b|^\s*\d\s*$",text,re.I)
            delegated=re.search(r'\bcolou?r[- ]?blind\w*|\bdaltoni\w*|\baccessib\w*|\bcvd\b|\b(?:you|your)\s+(?:choose|pick|decide|choice)\b|\bwhatever\b',spoken)
            if unnamed and (delegated or (accepting and all(stem(u) in offered for u in unnamed))):
                unnamed=[]
            # "restore it as it was" after "E had RED_HOT; restoring the file's colours"
            # (2026-11-12): the LUT it had before, named in the last reply, is not invented
            reverting=re.search(r'\b(?:as it was|as they were|as before|like before|put (?:it|them) back|revert\w*|go back|'
                                r'undo|previous|comme avant|remet\w*)\b',spoken)
            compact=re.sub(r'[^a-z]','',offered)
            if unnamed and reverting and all(stem(u).replace(' ','') in compact for u in unnamed):
                unnamed=[]
            if unnamed and offered_default and (accepting or re.search(r'\b(?:default|own|original|restor\w*|back)\b',spoken)):
                unnamed=[u for u in unnamed if stem(u) not in ('default','none')]
            if re.search(r'\bgr[ae]y ?scale\b|\bblack (?:and|&) white\b|\bmonochrome\b|\bnoir et blanc\b|\bniveaux de gris\b',spoken):
                unnamed=[u for u in unnamed if stem(u)!='gray']        # "black and white" is GRAY
            if unnamed:
                from ..errors import NeedsClarification
                raise NeedsClarification('The request does not name the colour table '+', '.join(unnamed)+". Do you want the image's own colours "
                                         'back (the default LUT of the file), or a LUT you name (e.g. GRAY, RED, GREEN, BLUE, MAGENTA, '
                                         'YELLOW_HOT; list_luts lists them all)? No LUT was changed.')
        greek=re.search(r'\b(?:panel|image|picture)\s+(alpha|beta|gamma|delta|epsilon|zeta|eta|theta|iota|kappa|lambda|mu|nu|xi|omicron|pi|rho|sigma|tau|upsilon|phi|chi|psi|omega)\b',text,re.I)
        if greek and not read_only and not any(greek[1].lower() in [str(x).lower() for x in p.get('letters',[])] for p in state.get('panel_references',[])):
            # "the letter from panel omega": no such panel, so nothing may be guessed.
            from ..errors import NeedsClarification
            raise NeedsClarification(f'There is no panel called {greek[1]} in this figure. Which panel do you mean? Nothing was changed.')
        columns=re.search(r'(?<![\w.])(-?\d+)\s+(?:pictures?|images?|panels?)\s+(?:per|on each|in each|in a|a)\s+row\b',text,re.I)
        if columns and operation=='arrange_live_images' and not args.get('row_counts') and args.get('columns')!=int(columns[1]):
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
            # the selection the request began with may be gone: the model cleared it
            # (select_live_objects clear=true) and was refused three times on the old one
            # (replay 2026-11-19, "and don't make it bold neither")
            try:
                now = (self.request('inspect').get('selection') or {}).get('selected_panels') or []
            except Exception:
                now = panels
            if len(now) != 1:
                return
            raise ValueError('Selected-letter request targets only panel ' + panels[0]['panel_id'] + '; no edit submitted. Use scope=selection or that panel_ids list.')

    @staticmethod
    def _quote_the_request(args, text):
        """A letter colour / background needs the user's words naming the letter
        (color_request / background_request). When the model leaves the field out but THIS
        request's own words name the letter, they are the quote: filled in, so the call is
        not refused and sent again (replays 2026-11-20: "make b letter red" refused, then
        accepted with the same words, with Mistral and Qwen alike). Words that do not name
        the letter are left to the guard, which still asks."""
        import re
        if not isinstance(args, dict) or not re.search(r'\b(?:letters?|lettering|labels?|lettre\w*)\b', str(text or ''), re.I):
            return
        quote = str(text).strip()
        if args.get('color') is not None and not args.get('color_request'):
            args['color_request'] = quote
        background = args.get('background')
        if background is not None and str(background).strip().lower() not in ('', 'none', 'transparent', 'no', 'null', 'clear') \
                and not args.get('background_request'):
            args['background_request'] = quote

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

    _UNCROP = (r"\s*(?:please\s+|(?:can|could)\s+you\s+)?(?:un-?crop|remove\s+(?:the\s+)?crop(?:ping)?|"
               r"reset\s+(?:the\s+)?crop(?:ping)?|undo\s+the\s+crop(?:ping)?|no\s+crop)\b"
               r"(?:\s+(?:it|this|that|them|of|from|on|panel|image|picture|the|[a-z]|please|again))*[\s.!?]*")

    @staticmethod
    def _crop_needs_a_look(args, text):
        """A crop chosen from what the image shows ("so the scale bar is hidden", "to the
        nuclei"), not from numbers the user gave or a crop removed."""
        import re
        sides = [args.get(s) for s in ('crop_left', 'crop_right', 'crop_top', 'crop_bottom')]
        if not any(v for v in sides if isinstance(v, (int, float))):
            return False                    # no crop or every side 0 (uncrop)
        if re.search(r'\d+(?:\.\d+)?\s*(?:px|pixels?|%|percent)|\b(?:by|of)\s+\d+\b|\bsame\s+(?:crop|as)\b|\bcrop(?:ping)?\s+of\b', text, re.I):
            return False                    # the user gave the numbers or another panel's crop
        return bool(re.search(r'\bcrop\w*|\bcut\b|\btrim\w*|\bhide\b|\bhidden\b|\bget\s+rid\b|\bremove\b', text, re.I))

    def _uncrop_completion(self, name, arguments, result, text):
        """"uncrop it": the host's readback already says every crop is 0, so the reply is
        written here instead of after another read and model call (user chat 2026-11-13:
        the crop was removed in 1.4 s, then a figure read and a 34 s answer)."""
        import re
        if name != 'transform_image' or result.get('is_error') or not re.fullmatch(self._UNCROP, text, re.I):
            return None
        args = arguments.get('arguments', {}) if 'arguments' in arguments else arguments
        sides = ('crop_left', 'crop_right', 'crop_top', 'crop_bottom')
        if set(args) - set(sides) - {'panel_ref'} or any(args.get(s) not in (0, None) for s in sides) or not args.get('panel_ref'):
            return None
        try:
            body = json.loads(result.get('content', ''))
        except (ValueError, TypeError):
            return None
        said = str(body.get('result', ''))
        if not body.get('document_changed') or any(f'{s}=0' not in said for s in sides):
            return None
        ref = str(args['panel_ref'])
        target = 'panel **' + ref + '**' if not re.fullmatch(r'[\d/]+', ref) else 'the panel'
        return f'Done: {target} is uncropped, its whole image is shown again (crop 0 on every side). Verified in the open figure.'

    _MORE_TO_DO = (r'\b(?:and|then|also|after(?:wards)?|before|plus|but|except|unless|if|check|verify|show|preview|'
                   r'et|puis|ensuite|aussi)\b|[;:]|,|\.\s+\S|\?')

    def _batch_completion(self, tool_name, arguments, result, text, state=None):
        """One instruction done as one batch, every item applied and read back by the
        figure: the reply is written here (2026-11-13: "rotate all images by 25 degrees"
        was done in 2 s, then an inspect and a re-read made the user wait 45 s)."""
        import re
        if tool_name != 'use_pyfigures_tool' or not arguments.get('batch') or result.get('is_error'):
            return None
        if str((state or {}).get('_last_reply') or '').rstrip().endswith('?'):
            # an answer to the assistant's question ("data plot"): the work is the request
            # before it, often several batches (chat 2026-11-19: the turn ended after the
            # first 6 of 20 files, "Done: add image (group_path=[]) on 6 items")
            return None
        if re.search(self._MORE_TO_DO, text.strip().rstrip('.!'), re.I):
            return None                        # more than one thing asked: the model goes on
        try:
            body = json.loads(result.get('content', ''))
        except (ValueError, TypeError):
            return None
        total = body.get('batch_total')
        if not body.get('verified') or body.get('errors') or not total or body.get('batch_done') != total:
            return None
        if str(arguments.get('tool_name', '')).startswith('add_') and any(
                int(n) > total for n in re.findall(r'\b(\d{1,3})\b', text)):
            return None                        # "the first 20 files": 6 added so far, the rest follows
        name = str(arguments.get('tool_name', 'the operation')).replace('_', ' ')
        shared = arguments.get('arguments') or {}
        refs = [str(i.get('panel_ref')) for i in arguments['batch'] if isinstance(i, dict) and i.get('panel_ref')]
        panels = list(dict.fromkeys(refs))     # 81 ROIs listed "panels b, b, b, ..." (replay, 2026-11-13)
        if len(refs) == total and len(panels) == total:
            where = 'panels **' + '**, **'.join(panels) + '**'
        elif panels:
            where = f'{total} items in panel{"s" if len(panels) > 1 else ""} **' + '**, **'.join(panels) + '**'
        else:
            where = f'{total} items'
        # what was set, in the user's terms: not where it went (group_path=[] read as an error)
        how = ', '.join(f'{k}={v}' for k, v in shared.items()
                        if k not in ('panel_ref', 'pyf_path', 'group_path', 'session_id', 'expected_revision')
                        and v not in ([], {}, '', None))
        return (f'Done: {name}' + (f' ({how})' if how else '') + f' on {where}, in one step. '
                'Each one was read back in the open figure.')

    def verified_completion(self, tool_name, arguments, result, state, text):
        import re
        if re.search(r'\b(?:select|highlight|pick)\b',text,re.I):return None
        batched = self._batch_completion(tool_name, arguments, result, text, state)
        if batched:
            return batched
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
        uncropped = self._uncrop_completion(name, arguments, result, text)
        if uncropped:
            return uncropped
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


    _EDITOR_THINGS = (r'\b(?:rois?|insets?|arrows?|annotations?|rectangles?|ellipses?|circles?|lines?|boxe?s?|shapes?|'
                      r'scale\s*bars?|crop\w*|rotat\w*|texts?|labels?|colou?rs?|luts?|channels?|pixel\s+size|'
                      r'positions?|sizes?|places?|ellipses?|ovals?|squares?|it|this|that|them|those|these)\b')
    _EDITOR_TABS = ((r'\bcrop\w*', 'crop'), (r'\brotat\w*', 'rotate'), (r'\b(?:colou?rs?|luts?|channels?|pixel\s+size)\b', 'scale'),
                    (r'\btexts?\b', 'text'))

    @staticmethod
    def _editor_tab_for(operation, args):
        """The panel editor tab where the user redoes what *operation* did."""
        if any(str(k).startswith('crop') for k in args) or operation in ('crop_image', 'uncrop_image'):
            return 'crop'
        if any(k in args for k in ('rotation', 'theta', 'angle', 'flip_h', 'flip_v')):
            return 'rotate'
        if operation in ('set_scale_bar', 'remove_scale_bar', 'set_lut', 'set_pixel_size') or 'channels' in args:
            return 'scale'
        if operation in ('add_annotation', 'change_text_size', 'restyle_texts'):
            return 'text'
        return 'annotations'

    def _panel_name(self, ref, state):
        """The letter the user sees for a panel id ("0/1" -> "b")."""
        import re
        if not re.fullmatch(r'[\d/]+', str(ref)):
            return str(ref)
        for p in (state or {}).get('panel_references') or []:
            if str(p.get('panel_id')) == str(ref) and p.get('letters'):
                return str(p['letters'][0])
        return 'the selected panel'

    def _named_panel(self, text, state):
        """The panel *text* names ("in b", "panel b", "of B", "#3"), checked against the figure."""
        import re
        refs = state.get('panel_references') or []
        letters = {str(l).lower(): str(l) for p in refs for l in (p.get('letters') or []) + [p.get('name')]
                   if l and len(str(l)) == 1}
        for m in re.finditer(r"\b(?:panel|image|picture|in|of|on|for)\s+([a-z])\b(?![\w'’])", text, re.I):
            letter = m.group(1).lower()
            at_end = re.fullmatch(r"\W*(?:(?:my\s*self|manually|by\s+hand|please|for\s+me|now|again)\W*)*",
                                  text[m.end():], re.I) is not None
            if letter in ('a', 'i') and not re.match(r'(?:panel|image|picture)\b', m.group(0), re.I) and not at_end:
                continue                    # "in a minute", "of I": only "panel a" (or "...crop in a") names a / i
            if letter in letters:
                return letters[letter]
        # "the b crop", "b's crop": a letter before a thing of a panel (user 2026-11-19:
        # "let me edit the b crop" opened the selected panel, g, on the crop tab)
        things = (r"(?:crop\w*|rois?|insets?|images?|panels?|annotations?|arrows?|scale\s*bars?|bars?|texts?|"
                  r"labels?|rotation|editor|channels?|colou?rs?|luts?)")
        for m in re.finditer(r"\b([a-z])(['’]s)?\s+" + things + r"\b", text, re.I):
            letter = m.group(1).lower()
            if letter in ('a', 'i') and not m.group(2):
                continue                    # "a crop", "I crop it": an article or a pronoun
            if letter in letters:
                return letters[letter]
        m = re.search(r"#\s?(\d+)\b", text)
        if m and 0 < int(m.group(1)) <= len(refs):
            return str(refs[int(m.group(1)) - 1].get('panel_id'))
        return None

    _REOPEN = (r"\b(?:re-?open|open\s+(?:it|this|that|them|the\s+\w+(?:\s+\w+)?)?\s*(?:again|back|once\s+more|one\s+more\s+time))\b")
    _EDITOR_SLIP = (r"\b(?:(?:i\s+)?(?:made|make|did)\s+a\s+(?:mistake|wrong\s+move|error)|"
                    r"(?:i\s+)?(?:pressed|clicked|hit)\s+(?:the\s+)?(?:cancel|ok|wrong\s+button)|closed\s+it|"
                    r"messed\s+(?:it\s+)?up|screwed\s+(?:it\s+)?up|oops|try\s+again|once\s+more|one\s+more\s+time)\b|^\W*again\W*$")
    _NOT_A_REOPEN = (r"\b(?:undo|revert|go\s+back|restore|put\s+it\s+back|make|set|change|remove|delete|add|move|"
                     r"rename|resize|colou?r|crop|rotate|export|save|message|meant|typo|wrote|asked)\b")

    def _reopen_editor(self, request):
        """"again i made a mistake" right after the chat opened an editor, "I said open
        it again", "reopen it": open that editor again (user chat 2026-11-13: the reply
        asked what the mistake was; "open it again" went through a tool search)."""
        import re
        last = getattr(self, '_last_editor', None)
        if not last or len(request.split()) > 14 or re.search(self._NOT_A_REOPEN, request, re.I):
            return None
        explicit = re.search(self._REOPEN, request, re.I)
        slip = re.search(self._EDITOR_SLIP, request, re.I) and getattr(self, '_turns_since_editor', 99) <= 2
        if not (explicit or slip):
            return None
        ref, tab = last
        name = ref if not re.fullmatch(r'[\d/]+', str(ref)) else 'the selected panel'
        title = {'annotations': 'Annotations', 'crop': 'Rotate + Crop', 'rotate': 'Rotate + Crop',
                 'scale': 'File Infos + Scale', 'text': 'Texts'}[tab]
        try:
            self.request('open_annotation_editor', {'panel_ref': ref, 'tab': tab})
        except Exception as exc:
            if 'ANNOTATION_EDITOR_OPEN' in str(exc) or 'already' in str(exc).lower():
                content = ('The panel editor is still open: make your changes there, then press **OK** to apply them '
                           'or **Cancel** to drop them.')
            else:
                return None
        else:
            content = (f'I opened the editor of panel **{name}** again, on its **{title}** tab. Make your change, then '
                       f'press **OK** to apply it or **Cancel** to drop it.')
            if slip and not explicit:
                content += (' If you pressed **OK** on a change you don\'t want, press the **Undo** button of the '
                            'figure (Ctrl+Z) first, or tell me to undo it.')
        self._turns_since_editor = 0
        return {'content': content, 'evidence': {'operation': 'open_annotation_editor', 'panel_ref': ref, 'tab': tab,
                                                 'operation_executed': False, 'self_edit': True, 'reopened': True}}

    def _open_editor_for_self_edit(self, request):
        """"I wanna edit the ROI of the inset in b", "let me edit it myself": open the
        panel editor at once instead of asking which ROI and what change (user chat
        2026-11-12: two questions before the editor opened)."""
        import re
        reopened = self._reopen_editor(request)
        if reopened:
            return reopened
        # "open the dioalog for me", "open its editor" (user chat 2026-11-12: typed with a typo)
        explicit = re.search(r"\bopen\s+(?:up\s+)?(?:the\s+|its\s+|his\s+|her\s+|a\s+|panel\s+\w+(?:['’]s)?\s+)?"
                             r"(?:panel\s+|image\s+|annotation\s+|edit(?:ing)?\s+)?(?:editor|di\w{0,3}log\w*|edit\s+window)\b",
                             request, re.I)
        if re.search(r"\b(?:don['’]?t|do\s+not|no\s+need\s+to|never)\s+open\b", request, re.I):
            explicit = None
        if not explicit and (not self._wants_to_edit_himself(request) or not re.search(self._EDITOR_THINGS, request, re.I)):
            return None
        if explicit and re.search(r'\b(?:export|save|print|preferences?|settings|file|journal|letters?\s+dialog)\b', request, re.I):
            return None                     # another dialog than the panel editor
        if re.search(r'\b(?:letters?|layout|rows?|columns?|figure|spacing|order)\b', request, re.I):
            return None                     # not things of one panel's editor
        if not explicit and re.search(r"\b(?:show|shwo|sow)\s+me\b|\bhow\s+(?:do|to|can|could|would|should)\b|\bteach\b|"
                                      r"\bwhere\b", request, re.I):
            # "show me how to do that manually" (a projection) is a guide, not this editor
            # (user chat 2026-11-23: it opened d's Annotations tab): the model answers
            return None
        try:
            state = self.request('inspect')
        except Exception:
            return None
        ref = self._named_panel(request, state)
        tab = next((t for pattern, t in self._EDITOR_TABS if re.search(pattern, request, re.I)), None)
        last_edit = getattr(self, '_last_edit', None)
        if ref is None and last_edit and getattr(self, '_turns_since_edit', 99) <= 2:
            # "have me edit it manually" right after the chat cropped a: a's crop, not the
            # selected panel (user chat 2026-11-23)
            ref, tab = last_edit[0], tab or last_edit[1]
        if ref is None:
            selected = (state.get('selection') or {}).get('selected_panels') or []
            if len(selected) == 1:
                ref = selected[0].get('panel_id')
        if ref is None:
            ref = getattr(self, '_last_named_panel', None)
        if ref is None:
            # unclear: ask, offering the editor of each panel (the user's rule: ask, with choices)
            names = [str(l) for p in (state.get('panel_references') or []) for l in (p.get('letters') or [])][:8]
            choices = '\n'.join(f'- Open the editor of panel **{n}** for you' for n in names) or \
                '- Select the panel (click it), then ask again: I open its editor for you'
            content = ('Which panel do you want to edit yourself?\n' + choices +
                       '\n- Or tell me the change (e.g. "move the ROI in b up") and I make it')
            return {'content': content, 'evidence': {'operation_executed': False, 'self_edit': True,
                                                     'clarification': 'which panel'}}
        tab = tab or 'annotations'
        name = self._panel_name(ref, state)
        try:
            self.request('open_annotation_editor', {'panel_ref': ref, 'tab': tab})
        except Exception as exc:
            if 'ANNOTATION_EDITOR_OPEN' in str(exc) or 'already' in str(exc).lower():
                content = ('The panel editor is already open: make your changes there, then press **OK** to apply them '
                           'or **Cancel** to drop them.')
            else:
                return None
        else:
            title = {'annotations': 'Annotations', 'crop': 'Rotate + Crop', 'rotate': 'Rotate + Crop',
                     'scale': 'File Infos + Scale', 'text': 'Texts'}[tab]
            content = (f'I opened the editor of panel **{name}** on its **{title}** tab. Click what you want to change '
                       f'(drag it to move it, drag a corner to resize it), then press **OK** to apply your changes or '
                       f'**Cancel** to drop them. I won\'t change anything meanwhile.')
        self._last_editor = (ref, tab)      # "I made a mistake" / "open it again" reopens it
        self._turns_since_editor = 0
        return {'content': content, 'evidence': {'operation': 'open_annotation_editor', 'panel_ref': ref, 'tab': tab,
                                                 'operation_executed': False, 'self_edit': True}}

    def _inset_cannot_move(self, request):
        """"move the smallest inset in b by 100 px to the right": an inset sits in a
        corner of its panel and has no free position; twice the model searched eight
        times for an offset and stopped (user chats 2026-11-13). Say so at once and
        offer what can be done."""
        import re
        if not re.search(r'\b(?:move|shift|nudge|slide|push|drag|displace)\w*\b', request, re.I) \
                or not re.search(r'\binsets?\b', request, re.I):
            return None
        # a distance; a bare direction ("move the inset up") may mean another corner
        if not re.search(r'\d+\s*(?:px|pixels?|%|mm)?|\b(?:a\s+bit|slightly|a\s+little|a\s+tad|further|closer)\b',
                         request, re.I):
            return None
        if re.search(r'\b(?:to|into|in)\s+(?:the\s+)?(?:other\s+)?(?:top|bottom|upper|lower)[\s-]*(?:left|right)\b|\bcorner\b|'
                     r'\b(?:roi|box|rectangle|region)\b', request, re.I):
            return None          # another corner, or the ROI it shows: the model can do it
        state = None
        try:
            state = self.request('inspect')
        except Exception:
            pass
        ref = self._named_panel(request, state or {}) if state else None
        name = f'panel **{ref}**' if ref else 'the panel'
        right = re.search(r'\bright\b', request, re.I)
        left = re.search(r'\bleft\b', request, re.I)
        corner = 'top right' if right else 'top left' if left else 'other'
        # the user usually means the ROI the inset shows (user, 2026-11-13): first choice,
        # worded as a request the model can run when clicked
        roi_request = re.sub(r'\b(the\s+)?((?:smallest|smaller|largest|larger|biggest|bigger|first|second|left|right|'
                             r'top|bottom|other|\w+est)\s+)?(insets?)\b',
                             lambda m: 'the ROI of the ' + (m.group(2) or '') + m.group(3), request, count=1, flags=re.I)
        roi_request = roi_request[:1].upper() + roi_request[1:]
        content = (f'Do you mean the ROI that the inset of {name} shows, or the inset itself? An inset cannot be '
                   f'moved by a distance: it always sits in a corner of its panel.\n'
                   f'- {roi_request} (the inset then shows the new region)\n'
                   f'- Put the inset in the {corner} corner\n'
                   f'- Open the panel editor so I can do it myself')
        return {'content': content, 'evidence': {'operation_executed': False, 'inset_has_no_free_position': True,
                                                 'clarification': 'ROI or inset'}}

    def preflight_manual_response(self, request):
        """Resolve a pure control-location question from reviewed help before model discovery."""
        import re
        self._turns_since_editor = getattr(self, '_turns_since_editor', 99) + 1
        self._turns_since_edit = getattr(self, '_turns_since_edit', 99) + 1
        try:
            state = None
            named = None
            if re.search(r"\b(?:panel|image|picture|in|of|on|for)\s+[b-hj-z]\b(?![\w'’])", request, re.I):
                state = self.request('inspect')
                named = self._named_panel(request, state)
            if named:
                self._last_named_panel = named      # "edit it myself" next turn means that panel
        except Exception:
            pass
        opened = self._open_editor_for_self_edit(request)
        if opened:
            return opened
        fixed = self._inset_cannot_move(request)
        if fixed:
            return fixed
        if not re.match(r'^\s*where\s+(?:is|are)\b', request, re.I):
            return None
        # Mixed questions/actions must retain the normal conversational/tool path.
        if re.search(r'\b(?:and|then|also)\s+(?:please\s+)?(?:do|apply|flip|rotate|change|set|move|remove|delete|make|swap|open)\b', request, re.I):
            return None
        answer = self.finalize_manual_response(request)
        if answer:
            self._guided = False
            offered = self.offer_gui_help(answer['content'])
            if offered:
                answer = {'content': offered, 'evidence': {**answer['evidence'], 'gui_help_offered': True}}
        return answer


    def finalize_manual_response(self,request):
        import re
        # "how many channels does this image have" asks for a number, not steps: it got the
        # channel-split guide (2026-11-12)
        asks_steps=re.sub(r'\bhow\s+(?:many|much|big|large|small|long|wide|tall|old|often)\b','',request,flags=re.I)
        manual=bool(re.search(r'\b(?:how|explain|tutorial|instructions?|shortcuts?)\b|\bwhere\s+(?:is|are|do|can|should)\b|\bwhat\s+if\b',asks_steps,re.I))
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

    _STYLE_WORDS = {'font_family': 'font', 'font_size': 'size', 'bold': 'bold', 'italic': 'italic',
                    'underline': 'underline', 'background': 'background box'}
    # (colour is left out: automatic letters are white on dark panels, black on light ones)

    def _verify_letter_consistency(self, request):
        """"Use consistent fonts for all letters": letter b stayed the only bold one with a
        white box and the reply said they were consistent (user chat 2026-11-12). Some
        letters still differing is said, with the choices to settle it."""
        import re
        if not (re.search(r'\b(?:cons?i?s?t[ae]n\w*|same|uniform\w*|identical|match\w*|harmoni[sz]\w*|alike)\b', request, re.I)
                and re.search(r'\b(?:letters?|fonts?|labels?|lettering)\b', request, re.I)):
            return None
        try:
            current = self.request('letter_state')
        except Exception:
            return None
        letters = [(str(a.get('text', '')), a) for p in current.get('panels', []) for a in p.get('letters', [])]
        if len(letters) < 2:
            return None
        differing = {}
        for field, word in self._STYLE_WORDS.items():
            values = [a.get(field) for _, a in letters]
            if any(v != values[0] for v in values):
                # the odd ones: the value fewer letters have
                counts = {}
                for v in values:
                    counts[repr(v)] = counts.get(repr(v), 0) + 1
                common = max(counts, key=counts.get)
                differing[word] = [t for t, a in letters if repr(a.get(field)) != common]
        if not differing:
            return None
        odd = sorted({t for ts in differing.values() for t in ts})
        what = '; '.join(f"{w}: {', '.join(ts)} differ" for w, ts in differing.items())
        listed = ', '.join(odd)
        content = (f'The letters are not all the same yet ({what}). Which do you want?\n'
                   f'- Make {listed} like the other letters\n'
                   f'- Make every letter like {odd[0]}\n'
                   f'- Keep {listed} different on purpose')
        return {'content': content, 'evidence': {'status': 'not_consistent', 'differing': differing}}

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
        # "the letter bold on every ROTATED panel" (2026-11-12) is a subset this check cannot
        # name: taken for "all letters", a correct result was sent back as unfinished
        if re.search(r'\b(?:all|every|each)\s+(?:of\s+)?(?:the\s+)?(?!panels?\b|letters?\b|images?\b|pictures?\b|automatic\b|auto\b|panel\b|existing\b|current\b|visible\b|my\b|these\b|those\b|figure\b)\w+\s+(?:panels?|images?|pictures?|letters?)\b',request,re.I):
            return None
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

    GUI_HELP_OFFER = 'Should I **highlight where to click**, or **open it for me**?'
    _GUIDING_TOOLS = ('show_me_where', 'show_me_how', 'open_annotation_editor', 'open_native_menu', 'use_native_gui')

    def offer_gui_help(self, reply):
        """User finding 2026-11-05: answers that tell how to do something in the
        GUI never offered to highlight the path or open it. The offer is added
        here, not left to the model: GUI steps get the two-option question,
        a list of choices that names GUI controls gets 'Show me where to click'.
        Nothing is added after the chat already guided or opened something."""
        import re
        if not reply or getattr(self, '_guided', False):
            return None
        if re.search(r'show me where|where to click|highlight (?:where|the path|it|them)|open (?:it|them|the [\w +-]{1,30}) for (?:you|me)', reply, re.I):
            return None
        gui = re.findall(r'double[- ]click|right[- ]click|\bclick\b|\btabs?\b|\bmenus?\b|\bdialog\b|\beditor\b|\bpress\s+\**OK\b|→|➜', reply, re.I)
        if len(gui) < 2:
            return None
        lines = reply.rstrip().splitlines()
        items = [i for i, line in enumerate(lines) if re.match(r'^\s*(?:\d+[.)]|[-*•])\s+\S', line)]
        if not items:
            return None
        questions = [i for i, line in enumerate(lines) if '?' in line]
        # choices: the question introduces the list or closes the answer right after it
        is_choice = 2 <= len(items) <= 7 and any(items[0] - 3 <= q < items[0] or q > items[-1] for q in questions)
        if is_choice:
            numbered = re.match(r'^(\s*)(\d+)[.)]\s', lines[items[-1]])
            entry = (numbered.group(1) + str(int(numbered.group(2)) + 1) + '. ') if numbered else '- '
            lines.insert(items[-1] + 1, entry + '**Show me where to click**')
            return '\n'.join(lines)
        return reply.rstrip() + '\n\n' + self.GUI_HELP_OFFER

    def finalize_response(self,request,reply,state):
        verified = self._verify_response(request, reply, state)
        content = verified['content'] if verified else reply
        offered = self.offer_gui_help(content)
        if offered is None:
            return verified
        evidence = dict(verified['evidence']) if verified else {}
        evidence['gui_help_offered'] = True
        return {'content': offered, 'evidence': evidence}

    def _verify_response(self,request,reply,state):
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
        consistency=self._verify_letter_consistency(request)
        if consistency:return consistency
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
        title='Current figure'
        if evidence['status']=='blocked':
            lines=[re.sub(r'^\[FAIL\]\s*','',b) for b in evidence.get('blockers',[])]
            content=title+' is not ready under the technical checks:\n'+''.join('\n- '+line for line in lines)
        elif evidence['status']=='technical_checks_passed':
            target_line=evidence.get('checks',{}).get('check_resolution',{}).get('report','').splitlines()
            content=title+' passes the measured technical checks for this target. '+(target_line[0] if target_line else '')+' Scientific content and statistical assumptions still require review.'
        else:
            content='Technical readiness is incomplete; no ready verdict can be given. Specify a valid journal/physical target and resolve unavailable checks.'
        return {'content':content,'evidence':evidence}

    def begin(self, text):
        self._quality_review_requested=False
        self._guided=False
        return self.request('action_begin', {'text': text})

    def finish(self, interrupted=False):
        return self.decorate(self.request('action_finish', {'interrupted': interrupted}))

    def control(self, action, ident=None):
        if action not in ('undo', 'redo', 'recover'):
            raise ValueError('Unsupported host control')
        return self.decorate(self.request('action_' + action, {'ident': ident} if ident else {}))


def attach_to_window(window, config, descriptor):
    """Embed this package in a running PyFigures prototype main window."""
    from qtpy_ai_sidecar import create_dock
    from .docking import dock_beside
    return dock_beside(window, create_dock(window, config, PyFiguresAdapter(descriptor)))
