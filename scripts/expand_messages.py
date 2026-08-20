"""یک‌بار: python -c \"from bot_flow import messages\" کافی است؛ برای فایل ساده:\npython scripts/expand_messages.py\n"""
from pathlib import Path
import base64, zlib
def main():
    d = Path(__file__).resolve().parents[1] / "bot_flow"
    blob = "".join((d / f"_msg_{i}.b64").read_text(encoding="ascii") for i in range(2))
    code = zlib.decompress(base64.b64decode(blob)).decode("utf-8")
    (d / "messages.py").write_text(code, encoding="utf-8")
    print("expanded messages.py", len(code))
if __name__ == "__main__":
    main()
