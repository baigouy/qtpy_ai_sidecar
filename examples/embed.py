"""Run from the repository root; requires a running tool-capable model backend."""
import sys
from qtpy.QtWidgets import QApplication, QMainWindow, QLabel
from qtpy.QtCore import Qt
from qtpy_ai_sidecar import create_dock
from qtpy_ai_sidecar.config import Config

app = QApplication(sys.argv)
window = QMainWindow()
window.setWindowTitle('Host application — embedded sidecar example')
window.setCentralWidget(QLabel('Your application GUI lives here.'))
dock = create_dock(window, Config.load('examples/demo.json'))
window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
app.aboutToQuit.connect(dock.shutdown)
window.resize(1100, 800)
window.show()
raise SystemExit(app.exec())
