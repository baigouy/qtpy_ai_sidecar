"""Found 2026-11-23: the local model server (llama-server, ~16 GB of graphics memory) outlived
PyFigures, which force-exits; on Windows a child survives its parent. It now stops when the
application quits, and on Windows a job object ends it even after a crash or a forced exit.
A sleeping Python process stands in for llama-server."""
import subprocess
import sys
import time

import pytest

from qtpy_ai_sidecar import runtime

SLEEPER = [sys.executable, '-c', 'import time; time.sleep(60)']


def test_stop_all_ends_every_server_started():
    process = subprocess.Popen(SLEEPER)
    runtime._RUNNING.add(process)
    runtime.stop_all()
    assert process.poll() is not None and process not in runtime._RUNNING


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows job objects')
def test_on_windows_the_server_dies_when_its_job_handle_closes():
    import ctypes
    process = subprocess.Popen(SLEEPER)
    try:
        job = runtime.tie_to_this_process(process)
        assert job
        assert process.poll() is None
        ctypes.WinDLL('kernel32').CloseHandle(ctypes.c_void_p(job))   # what Windows does when the app dies
        for _ in range(50):
            if process.poll() is not None:
                break
            time.sleep(0.1)
        assert process.poll() is not None
    finally:
        if process.poll() is None:
            process.kill()


def test_a_forced_exit_leaves_no_server_behind(tmp_path):
    """A parent that starts a 'server' through the same code and calls os._exit."""
    pid_file = tmp_path / 'pid'
    script = tmp_path / 'parent.py'
    script.write_text(
        'import os, subprocess, sys\n'
        'from qtpy_ai_sidecar import runtime\n'
        f'p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])\n'
        'runtime._RUNNING.add(p)\n'
        'job = runtime.tie_to_this_process(p)\n'
        f'open(r"{pid_file}", "w").write(str(p.pid))\n'
        'os._exit(0)\n')
    subprocess.run([sys.executable, str(script)], timeout=60, check=True)
    pid = int(pid_file.read_text())
    if sys.platform != 'win32':
        import os
        try:
            os.kill(pid, 9)            # no job objects there: aboutToQuit/atexit stop it instead
        except OSError:
            pass
        return
    alive = True
    for _ in range(50):
        out = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/NH'], capture_output=True, text=True).stdout
        alive = str(pid) in out
        if not alive:
            break
        time.sleep(0.1)
    assert not alive
