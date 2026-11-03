"""Keep one Qt application alive for the entire GUI test session."""
import pytest

@pytest.fixture(scope='session',autouse=True)
def qt_application_lifetime():
    from qtpy.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    yield app
    app.processEvents()


@pytest.fixture(autouse=True)
def private_provider_list(tmp_path,monkeypatch):
    """Tests never read or write the user's own providers.json."""
    from qtpy_ai_sidecar import providers
    monkeypatch.setattr(providers,'path',lambda:tmp_path/'providers.json')


def pytest_sessionstart(session):
    from pathlib import Path
    marker=Path(__file__).resolve().parents[1]/'validation/pyfigures/CLAUDE_ACTIVE_RUN.json'
    if marker.exists():
        pytest.exit('Claude Qt/model run is active. Wait until CLAUDE_ACTIVE_RUN.json is removed.',returncode=4)
