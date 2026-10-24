"""Standalone branding; embedded docks preserve the host identity."""
import sys
from pathlib import Path
from qtpy.QtGui import QIcon

def initialize_standalone():
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('QtPyAISidecar.Desktop.0.1')

def application_icon():
    return QIcon(str(Path(__file__).parent / 'resources' / 'sidecar.svg'))
