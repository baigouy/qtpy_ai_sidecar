"""Canonical font oracle: use the same native report as the MCP, not offscreen Qt."""
import json

def read_font_truth(queries,list_fonts):
    """Call before model startup; keep exact evidence and refuse malformed truth."""
    status={};evidence={}
    for query in sorted(set(queries)):
        raw=list_fonts(query=query)
        report=json.loads(raw) if isinstance(raw,str) else raw
        check=report.get('font_check') if isinstance(report,dict) else None
        if not isinstance(check,dict) or check.get('requested','').casefold()!=query.casefold():
            raise ValueError('Missing exact font_check for '+query)
        if not isinstance(check.get('installed'),bool):
            raise ValueError('Missing boolean installation status for '+query)
        if not check.get('drawn_as') or not isinstance(check.get('alternatives'),list):
            raise ValueError('Incomplete substitution evidence for '+query)
        status[query]=check
        evidence[query]=report
    return status,evidence
