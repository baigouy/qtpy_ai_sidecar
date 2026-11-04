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
READ_ONLY_TOOLS = frozenset({'inspect_litsearch', 'read_paper', 'show_figure', 'get_evidence',
                             'review_material', 'list_watches', 'list_notes', 'check_papers'})
# change what the GUI shows (results, selection, summary) or open a page, never the user's files
VIEW_TOOLS = frozenset({'search_local', 'search_external', 'show_paper', 'set_summary', 'restore_view',
                        'open_papers'})
# change files: watches, exports, the PDF index, downloads, tags / notes, saved reviews
DATA_TOOLS = frozenset({'manage_watch', 'export_results', 'library', 'download_papers', 'tag_papers',
                        'note_paper', 'screen_papers', 'saved_reviews'})
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
        action = (arguments or {}).get('action', 'list')
        if tool_name == 'library':      # list / duplicates read; the other actions act
            return action in ('list', 'duplicates')
        if tool_name == 'saved_reviews':
            return action == 'list'
        if tool_name == 'screen_papers':    # without papers: the counts only
            return not (arguments or {}).get('papers')
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
            'Call set_summary only when the user wants the summary shown in litsearch; it reports any cited '
            'label that does not exist. '
            'REVIEWS: for a review of chosen papers, guided by the points the user wants addressed, call '
            'review_material(papers=labels, points=the user\'s questions as given); write one cited section per '
            'point from those passages only, say which papers are silent on a point, show it with set_summary, '
            'check it with get_evidence(summary="shown"), and offer saved_reviews(action="save") to keep it. '
            'For a comparison table, review_material with one point per column, one row per paper (page in '
            'brackets, "not reported" otherwise), shown as a Markdown table and saved with '
            'export_results(table=[{"paper": "L1", ...}]) as csv, md or docx. export_results md / docx number '
            'the citations of the Summary tab with a reference list (style vancouver, apa or nature). '
            'Before citing papers in a review, offer check_papers (retractions, corrections); check_papers('
            'published_versions=True) finds the journal version of preprints, only when the user asks. '
            'To cite in Word / LibreOffice, export_results(labels=["cited"]) to a .ris named after the review; '
            'the user imports it in Zotero (File > Import: a collection of that name, PDFs attached) and cites '
            'with the Zotero plugin. '
            'Any papers= may be ["tag:to-read"] (a reading list; it replaces the results shown). '
            'UNDO: every view a tool replaces is kept; inspect_litsearch lists the history, restore_view(n) '
            'brings one back. '
            'SEARCH: search_local and search_external REPLACE the results shown unless append=True. '
            'search_external takes since/until dates, sort="newest" or "cited" (most cited first, OpenAlex '
            'counts), openalex_results (all fields, not only biomedicine), ids (PMIDs, DOIs, arXiv IDs) to '
            'fetch known papers, or related_to (a label, PMID or DOI) with relation "similar", "citing" or '
            '"references". search_local(paper=L2) searches inside one paper. read_paper(P#, full_text=True) '
            'reads an open-access article in full. show_figure returns a figure from a local PDF; with only a '
            'query, the most relevant figure in the whole library. '
            'LIBRARY: library "list" the indexed papers (external results already indexed carry in_library), '
            '"duplicates", "index" a folder and "stop" it (background jobs: say they started; never claim a '
            'running job is done; jobs show progress), "remove" papers only when the user asks, "import" a '
            'Zotero / EndNote .ris or .bib export. download_papers fetches only free legal PDFs of P results '
            'into the library and indexes them; for the others, offer open_papers so the user downloads them '
            'by hand (also whenever the user prefers to). tag_papers / note_paper keep the user\'s reading '
            'lists and notes (write a note only with what the user asked to note); list_notes lists them. '
            'screen_papers records include / exclude / maybe decisions, with the user\'s reason, for a named '
            'review and returns the counts. '
            'WATCHES: manage_watch action="save" keeps every setting not given; ask before overwriting a '
            'different existing watch; "delete" only when asked; "run" starts a background job. weekly='
            '"Monday 09:00" or "off" (Windows only); cites= a PMID or DOI watches the papers citing it; '
            'download_to= a library folder downloads new open-access PDFs; follow_preprints=True (only when '
            'asked) reports when followed preprints are published. list_watches(report=...) reads a past run. '
            'export_results writes HTML, BibTeX, RIS, Markdown, Word or CSV; ask before replacing a file. '
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
