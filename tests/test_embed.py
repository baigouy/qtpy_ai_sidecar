from qtpy.QtWidgets import QApplication, QMainWindow
from qtpy_ai_sidecar.config import Config
from qtpy_ai_sidecar.adapters.pyfigures import attach_to_window

def test_packaged_sidecar_embeds_in_host(tmp_path):
    app = QApplication.instance() or QApplication([])
    host = QMainWindow()
    name = app.applicationName()
    dock = attach_to_window(host, Config(state_dir=str(tmp_path)), tmp_path / 'bridge.json')
    host.show()
    app.processEvents()
    assert dock.parent() is host
    assert not dock.isFloating()
    assert dock.isVisible()
    assert app.applicationName() == name
    dock.shutdown()
    host.close()
