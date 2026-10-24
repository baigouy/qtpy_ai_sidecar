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
        return {key: result.get(key) for key in ('selection', 'verified_letter_specification', 'panel_references', 'last_canvas_click', 'revision', 'dirty')}

    def context_instructions(self, state):
        selection = state.get('selection') or {}
        return ('Swap named panels/images by default: swap b and c means exchange image panels, including obvious connector typos. Use swap_live_panels target=images. Only exchange letter TEXT when explicitly requested. Ask only if target references do not uniquely resolve. '
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
        read_only = operation and (operation.startswith(('inspect_', 'get_', 'list_', 'check_', 'describe_', 'audit_', 'explain_')) or operation in ('preview_figure', 'find_pyfigures_tools', 'readability'))
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

    def begin(self, text, preview=False):
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
