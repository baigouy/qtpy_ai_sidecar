"""Optional host features. MCP-only applications work without an adapter."""
from typing import Protocol


class HostAdapter(Protocol):
    """Methods run in the worker. Marshal native GUI access to its main thread.

    context/begin/finish/control must return JSON-serializable data. A finish
    result can expose controls=["undo", "redo", "apply", "discard"]. Only expose
    capabilities the host actually implements. Do not infer success from transport.
    """
    def context(self) -> dict: ...
    def begin(self, text: str, preview: bool = False) -> dict: ...
    def finish(self, interrupted: bool = False) -> dict: ...
    def control(self, action: str, ident: str | None = None) -> dict: ...


class NullAdapter:
    supports_preview = False

    def context(self):
        return {}

    def begin(self, text, preview=False):
        return {}

    def finish(self, interrupted=False):
        return {}

    def control(self, action, ident=None):
        raise ValueError('This application has no host action adapter')
