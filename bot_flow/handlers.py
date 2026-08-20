"""Handlers package entry — loads full implementation from base64 chunks."""
from __future__ import annotations

import base64
from pathlib import Path

_dir = Path(__file__).resolve().parent
_code = base64.b64decode(
    "".join((_dir / f"_hchunk_{i}.b64").read_text(encoding="ascii") for i in range(7))
).decode("utf-8")
exec(compile(_code, str(_dir / "handlers_impl.py"), "exec"), globals())
del base64, Path, _dir, _code
