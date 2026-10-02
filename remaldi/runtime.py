import fcntl
import os
from pathlib import Path

from .errors import ControlError


def runtime_dir() -> Path:
    path = Path(os.environ.get("REMALDI_RUNTIME_DIR", str(Path.home() / "Library/Caches/remaldi")))
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if path.is_symlink() or not path.is_dir() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ControlError(
            "unsafe_runtime_directory",
            "Runtime directory must be owned by this user with mode 0700.",
        )
    if len(os.fsencode(path / "control.sock")) >= 104:
        raise ControlError(
            "runtime_path_too_long",
            "Choose a shorter REMALDI_RUNTIME_DIR for the Unix socket.",
        )
    return path


def lock_file(path: Path, blocking: bool = True) -> int:
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
    except BaseException:
        os.close(fd)
        raise
    return fd
