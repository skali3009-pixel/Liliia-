"""Use an actual Bash runtime for shell checks on Linux and Windows."""
import os
from pathlib import Path
import shutil


def native_bash():
    if os.name == "nt":
        git_bash = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe"
        if git_bash.exists():
            return str(git_bash)
    return shutil.which("bash")
