"""Tiny application-independent MCP document, with persistence across connections."""
import json
from pathlib import Path
import os
from mcp.server.fastmcp import FastMCP

server = FastMCP('Sidecar demo document', instructions='A small demo document. Inspect actual state after editing before reporting success. Use set_all_labels for all labels, not one call per label.')
path = Path(os.environ.get('SIDECAR_DEMO_DOCUMENT', str(Path.home() / '.qtpy_sidecar_demo.json')))


def read():
    return json.loads(path.read_text()) if path.exists() else {'title': 'Demo document', 'labels': ['a', 'b', 'c', 'd'], 'color': 'black'}


@server.tool()
def inspect_document() -> dict:
    """Read the complete current demo document and label color."""
    return read()


@server.tool()
def set_all_labels(color: str) -> dict:
    """Set all demo label colors in one operation; returns verified before/after."""
    if color not in ('black', 'white', 'red', 'blue', 'green'):
        raise ValueError('Use black, white, red, blue or green')
    before = read()
    after = {**before, 'color': color}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(after), encoding='utf-8')
    return {'changed': before != after, 'before': before, 'verified_after': read()}


if __name__ == '__main__':
    server.run()
