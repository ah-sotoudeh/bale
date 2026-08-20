"""گسترش فایل‌های متنی برای ویرایش دستی.
python scripts/expand_messages.py
"""
from pathlib import Path
import base64, zlib

def expand(prefix: str, out_name: str, n: int):
    d = Path(__file__).resolve().parents[1] / "bot_flow"
    blob = "".join((d / f"_{prefix}_{i}.b64").read_text(encoding="ascii") for i in range(n))
    code = zlib.decompress(base64.b64decode(blob)).decode("utf-8")
    (d / out_name).write_text(code, encoding="utf-8")
    print("wrote", out_name, len(code))

if __name__ == "__main__":
    expand("msg", "messages.py", 2)
    expand("han", "handlers.py", 5)
