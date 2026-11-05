"""Importing the package does not load Qt or start a model/server."""
__version__ = "0.1.2"


def create_dock(parent, config, adapter=None):
    """Create an embeddable QDockWidget; the host owns QApplication."""
    from .widgets import AssistantDock
    return AssistantDock(config, adapter=adapter, parent=parent)
