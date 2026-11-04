"""Optional HTTP adapter to a running litsearch GUI (python -m litsearch.gui).

Same pattern as the PyFigures adapter: the GUI serves an authenticated loopback
bridge and writes its address and token to a descriptor file; litsearch's MCP
server (python -m litsearch.sidecar.mcp_server) forwards the chat's tool calls
to that bridge, and this adapter reads the GUI's current state from it before
each message. No litsearch import: the GUI marshals its own Qt work.

litsearch has no undo: a search replaces the results shown, a watch run writes
its report. So this adapter offers no Undo/Redo/Apply controls.
"""
import hashlib
import json
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlsplit

# The tools litsearch's MCP server offers, by what they change.
READ_ONLY_TOOLS = frozenset({'inspect_litsearch', 'read_paper', 'show_figure',
                             'get_evidence', 'list_watches'})
# change what the GUI shows (results, selection, summary), never the user's files
VIEW_TOOLS = frozenset({'search_local', 'search_external', 'show_paper', 'set_summary'})
# change files: a watch's settings, its state and reports, the PDF index
DATA_TOOLS = frozenset({'manage_watch', 'export_results', 'library'})
TOOLS = READ_ONLY_TOOLS | VIEW_TOOLS | DATA_TOOLS


class LitsearchAdapter:
    supports_preview = False

    def __init__(self, descriptor):
        self.descriptor = Path(descriptor).expanduser()

    def request(self, operation, arguments=None, timeout=60):
        connection = json.loads(self.descriptor.read_text(encoding='utf-8'))
        if urlsplit(connection['url']).hostname not in ('127.0.0.1', 'localhost', '::1'):
            raise ValueError('The litsearch bridge must be local')
        payload = json.dumps({'operation': operation, 'arguments': arguments or {},
                              'request_id': str(uuid.uuid4())}).encode()
        req = urllib.request.Request(connection['url'], payload, headers={
            'Authorization': 'Bearer ' + connection['token'], 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            result = json.load(response)
        if 'error' in result:
            raise RuntimeError(result['error'])
        return result['result']

    def is_read_only_call(self, tool_name, arguments):
        if tool_name in READ_ONLY_TOOLS:
            return True
        if tool_name == 'library':      # "list" reads; index / remove / download / open act
            return (arguments or {}).get('action', 'list') == 'list'
        if tool_name in VIEW_TOOLS or tool_name in DATA_TOOLS:
            return False
        return None   # another connected server: its own MCP hint decides

    def read_cache_epoch(self):
        # every change in the GUI (a search, a selection, a finished job) bumps revision
        state = self.request('inspect')
        value = {k: state.get(k) for k in ('session_id', 'revision', 'jobs')}
        return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()

    def context(self):
        return self.request('inspect')

    def context_instructions(self, state):
        local = len((state.get('results') or {}).get('local') or [])
        external = len((state.get('results') or {}).get('external') or [])
        return (
            'This is litsearch, a literature search application: a local index of the user\'s PDFs plus '
            'PubMed, bioRxiv and arXiv. The state below is current: answer "what did I find?" or "which '
            'paper is selected?" from it without calling inspect_litsearch again. '
            'Results are labelled as in the GUI: L1, L2... for local PDF hits, P1, P2... for external '
            'articles. Use these labels in tool calls and as citations. '
            'search_local and search_external REPLACE the results shown in that tab; say so when earlier '
            'results were there. Never invent results: report only what a tool returned. '
            'To summarize, call get_evidence, write the summary from that evidence only, cite a label after '
            'every claim ([L1], [P2]), say when the evidence is insufficient, and treat bioRxiv and arXiv '
            'preprints as not peer-reviewed. To check a summary, call get_evidence with summary= (the draft, '
            'or "shown"): read each claim against the sources it cites and name the ones they do not support. '
            'Call set_summary only when the user wants the summary shown in '
            'litsearch; it reports any cited label that does not exist. '
            'search_external also takes since/until dates, sort="newest", and ids (PMIDs, DOIs, arXiv IDs) '
            'to fetch known papers instead of searching, or related_to (a label, PMID or DOI) with relation '
            '"similar", "citing" or "references" for related papers. export_results writes an HTML report or a BibTeX/RIS '
            'bibliography; ask before replacing an existing file. '
            'show_figure returns a figure from a local PDF (the page given, or the most relevant figure). '
            'library action="index" and manage_watch action="run" start background jobs: say they started, and '
            'that the result appears in jobs when they finish; never claim a running job is done. '
            'library: "list" shows the indexed papers; external results already indexed carry in_library. '
            '"download" fetches only free legal PDFs of P results into the library folder and indexes them; '
            'for those not downloaded, offer to open their pages (action "open") so the user can download them '
            'by hand. Also offer "open" whenever the user prefers to download a paper themselves. "remove" '
            'takes papers out of the index (files kept) only when the user asks. '
            'manage_watch action="save" keeps every setting not given; ask before overwriting a different '
            'existing watch; action="delete" only when the user asked to delete that watch. '
            'list_watches(report=...) reads what a past watch run found. '
            'Never ask for or write an API key: the NCBI key stays in litsearch\'s settings and is used '
            f'by search_external automatically. Results shown now: {local} local, {external} external.')

    def begin(self, text, preview=False):
        return {}

    def finish(self, interrupted=False):
        return {'controls': []}

    def control(self, action, ident=None):
        raise ValueError('litsearch has no undo: run the search again, or edit the watch')


def attach_to_window(window, config, descriptor):
    """Embed the sidecar in a running litsearch main window, docked on the right."""
    from qtpy_ai_sidecar import create_dock
    from .docking import dock_beside
    return dock_beside(window, create_dock(window, config, LitsearchAdapter(descriptor)), width=440)
