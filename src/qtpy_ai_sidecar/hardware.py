"""Which local model fits this computer: its graphics memory (NVIDIA, read with nvidia-smi)
or, on Apple Silicon, its unified memory. Nothing is sent anywhere."""
import os
import platform
import shutil
import subprocess

# repository, label, the memory it needs to run with the chat's 64k context (GiB, Q4_K_M)
LOCAL_MODELS = [
    ('lmstudio-community/Qwen3.8-27B-GGUF', 'Qwen3.8 27B: best results, needs about 20 GB of graphics memory', 20),
    ('lmstudio-community/Qwen3.5-9B-GGUF', 'Qwen3.5 9B: single requests, about 8 GB of graphics memory', 8),
    ('lmstudio-community/Qwen3.5-4B-GGUF', 'Qwen3.5 4B: small graphics cards or no graphics card (slow)', 0),
]
# approximate download (Q4_K_M model + its vision projector), GB
DOWNLOAD_GB = {'lmstudio-community/Qwen3.8-27B-GGUF': 18, 'lmstudio-community/Qwen3.5-9B-GGUF': 7,
               'lmstudio-community/Qwen3.5-4B-GGUF': 3}


def gpu_memory_gib():
    """Total memory of the largest NVIDIA graphics card, in GiB; None when none is found."""
    exe = shutil.which('nvidia-smi')
    if not exe:
        return None
    try:
        out = subprocess.run([exe, '--query-gpu=memory.total', '--format=csv,noheader,nounits'],
                             capture_output=True, text=True, timeout=10,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
        sizes = [float(line) / 1024 for line in out.split() if line.strip().replace('.', '', 1).isdigit()]
        return max(sizes) if sizes else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def system_memory_gib():
    """Total system memory in GiB, or None."""
    try:
        import psutil
        return psutil.virtual_memory().total / 1024**3
    except Exception:
        pass
    if hasattr(os, 'sysconf'):
        try:
            return os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES') / 1024**3
        except (ValueError, OSError):
            pass
    return None


def apple_silicon():
    return platform.system() == 'Darwin' and platform.machine() in ('arm64', 'aarch64')


def recommended_model(gpu_gib=None, ram_gib=None, unified=False):
    """(repository, why) of the largest model this memory runs. On Apple Silicon the graphics
    share the system memory, of which about 3/4 can be given to the model."""
    usable = (ram_gib or 0) * 0.75 if unified else gpu_gib
    for repo, label, need in LOCAL_MODELS:
        if usable is not None and usable >= need and need:
            kind = 'unified memory' if unified else 'graphics memory'
            return repo, f'{label} (this computer: {usable / (0.75 if unified else 1):.0f} GB of {kind})'
    repo, label, _ = LOCAL_MODELS[-1]
    if usable is None:
        return repo, f'{label} (no graphics card found)'
    return repo, f'{label} (this computer: {usable / (0.75 if unified else 1):.0f} GB)'


def recommend_for_this_computer():
    if apple_silicon():
        return recommended_model(ram_gib=system_memory_gib(), unified=True)
    return recommended_model(gpu_gib=gpu_memory_gib())
