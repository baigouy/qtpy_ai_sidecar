"""User 2026-11-23: "make the default dl local model qwen 27B maybe or have it in the dropdown,
maybe adjust the model by default in dropdown to GPU mem/system". The model library lists
Qwen3.8 27B, 9B and 4B and starts on the largest one this computer's memory runs."""
import pytest

from qtpy_ai_sidecar import hardware


@pytest.mark.parametrize('gpu, repo', [(24, 'Qwen3.8-27B'), (20, 'Qwen3.8-27B'), (12, 'Qwen3.5-9B'),
                                       (8, 'Qwen3.5-9B'), (6, 'Qwen3.5-4B'), (None, 'Qwen3.5-4B')])
def test_graphics_memory_picks_the_model(gpu, repo):
    got, why = hardware.recommended_model(gpu_gib=gpu)
    assert got == f'lmstudio-community/{repo}-GGUF', (gpu, got)
    assert ('(no graphics card found)' in why) == (gpu is None)
    assert gpu is None or f'this computer: {gpu} GB' in why


@pytest.mark.parametrize('ram, repo', [(64, 'Qwen3.8-27B'), (32, 'Qwen3.8-27B'), (16, 'Qwen3.5-9B'), (8, 'Qwen3.5-4B')])
def test_apple_silicon_uses_its_unified_memory(ram, repo):
    got, why = hardware.recommended_model(ram_gib=ram, unified=True)
    assert got == f'lmstudio-community/{repo}-GGUF', (ram, got)
    assert f'this computer: {ram} GB' in why


def test_the_dialog_starts_on_the_recommended_model_and_its_q4_k_m(monkeypatch):
    from qtpy_ai_sidecar import library
    monkeypatch.setattr(hardware, 'recommend_for_this_computer',
                        lambda: ('lmstudio-community/Qwen3.8-27B-GGUF', 'Qwen3.8 27B (this computer: 24 GB)'))
    dialog = library.LibraryDialog(config=object())
    repos = [dialog.repositories.itemText(i) for i in range(dialog.repositories.count())]
    assert repos[0] == 'lmstudio-community/Qwen3.8-27B-GGUF' and len(repos) == 3
    assert dialog.repositories.currentText() == 'lmstudio-community/Qwen3.8-27B-GGUF'
    assert dialog.query.text() == 'Qwen3.8-27B-GGUF' and '24 GB' in dialog.recommendation.text()
    files = [{'name': n, 'size': 2**30} for n in ('m-Q8_0.gguf', 'm-Q4_K_M.gguf', 'm-Q6_K.gguf')]
    dialog.receive('files', files)
    assert dialog.files.currentRow() == 1 and 'Q4_K_M selected' in dialog.status.text()
    dialog.deleteLater()


def test_no_nvidia_smi_means_no_graphics_memory(monkeypatch):
    monkeypatch.setattr(hardware.shutil, 'which', lambda name: None)
    assert hardware.gpu_memory_gib() is None
