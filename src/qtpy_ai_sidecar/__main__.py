import argparse
import sys
from .config import Config


def main():
    parser = argparse.ArgumentParser(description='Standalone QtPy AI Sidecar')
    parser.add_argument('--config', help='Optional JSON application/MCP configuration')
    args = parser.parse_args()
    if args.config:
        config = Config.load(args.config)
    else:
        folder = Config().storage()
        folder.mkdir(parents=True, exist_ok=True)
        default = folder / 'application.json'
        if not default.exists():
            default.write_text('{}', encoding='utf-8')
        config = Config.load(default)
    adapter = None
    if config.adapter:
        if config.adapter.get('type') != 'pyfigures':
            parser.error('Unknown adapter; embed the widget to supply a custom adapter')
        from .adapters.pyfigures import PyFiguresAdapter
        adapter = PyFiguresAdapter(config.adapter['descriptor'])
    from qtpy.QtWidgets import QApplication, QMainWindow
    from qtpy.QtCore import Qt
    from .widgets import AssistantDock
    from .branding import initialize_standalone, application_icon
    initialize_standalone()
    app = QApplication(sys.argv[:1])
    app.setApplicationName('QtPy AI Sidecar')
    app.setWindowIcon(application_icon())
    window = QMainWindow()
    window.setWindowIcon(application_icon())
    window.setWindowTitle(config.application + ' · AI Sidecar')
    dock = AssistantDock(config, adapter, window)
    dock.setWindowIcon(application_icon())
    window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
    dock.setFeatures(dock.DockWidgetFeature.NoDockWidgetFeatures)
    window.resize(630, 860)
    app.aboutToQuit.connect(dock.shutdown)
    window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
