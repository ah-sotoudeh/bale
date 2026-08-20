"""متن‌های UI — ویرایش: python scripts/expand_messages.py سپس bot_flow/messages.py را باز کنید."""
from __future__ import annotations
import base64, zlib
from pathlib import Path
_dir = Path(__file__).resolve().parent
_blob = "".join((_dir / f"_msg_{i}.b64").read_text(encoding="ascii") for i in range(2))
_code = zlib.decompress(base64.b64decode(_blob)).decode("utf-8")
exec(compile(_code, str(_dir / "messages_data.py"), "exec"), globals())
del base64, zlib, Path, _dir, _blob, _code
