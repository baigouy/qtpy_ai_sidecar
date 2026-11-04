"""Docking an AssistantDock beside a host application's main window, shared by
the host adapters (PyFigures, litsearch)."""


def dock_beside(window, dock, width=480):
    """Put *dock* on the right of *window*, never wider than 40% of it (message
    and choice size hints must never steal the host's own width), and keep it
    as window.local_chat_dock. Returns the dock."""
    from qtpy.QtCore import Qt, QObject, QEvent
    from qtpy_ai_sidecar.branding import application_icon
    dock.setWindowIcon(application_icon())
    dock.setMinimumWidth(320)
    dock.setMaximumWidth(560)

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
    window.resizeDocks([dock], [width], Qt.Orientation.Horizontal)
    return dock
