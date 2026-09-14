"""Strict package-manager identity, including WinGet activation aliases."""
from __future__ import annotations

from pathlib import Path

# Documented Windows IO_REPARSE_TAG_APPEXECLINK; never parse its private payload.
_APPEXECLINK = 0x8000001B


def resolve_manager_identity(path: Path, manager: str, platform: str) -> Path:
    """Preserve invocation separately; return the verified regular image target."""
    if not path.is_absolute():
        raise OSError("manager invocation is not absolute")
    if (platform == "Windows" and manager == "winget"
            and getattr(path.lstat(), "st_reparse_tag", None) == _APPEXECLINK):
        # Deferred import keeps the shared resolver independent of executor setup.
        from .provider_execution import run_bounded_command_with_image

        try:
            result, image = run_bounded_command_with_image((str(path), "--version"), 10)
        except Exception as error:
            raise OSError(f"WinGet activation identity probe failed: {error}") from error
        if result.returncode != 0 or not result.stdout.strip():
            raise OSError("WinGet activation identity probe was unsuccessful")
        if not isinstance(image, str) or not image or "\0" in image:
            raise OSError("WinGet activation image is malformed")
        target = Path(image)
        if not target.is_absolute():
            raise OSError("WinGet activation image is not absolute")
    else:
        target = path
    if not target.is_file():
        raise OSError("manager image is not a regular file")
    return target.resolve(strict=True)
