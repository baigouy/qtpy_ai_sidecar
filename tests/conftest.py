"""Keep one Qt application alive for the entire GUI test session."""
import pytest

@pytest.fixture(scope='session',autouse=True)
def qt_application_lifetime():
    from qtpy.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    yield app
    app.processEvents()


def pytest_sessionstart(session):
    from pathlib import Path
    marker=Path(__file__).resolve().parents[1]/'validation/pyfigures/CLAUDE_ACTIVE_RUN.json'
    if marker.exists():
        pytest.exit('Claude Qt/model run is active. Wait until CLAUDE_ACTIVE_RUN.json is removed.',returncode=4)
