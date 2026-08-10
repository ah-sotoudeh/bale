#!/usr/bin/env python3
"""تشخیص ارسال لینک‌یار به کانال — resolve / عضویت / ادمین / send"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / '.env')
except ImportError:
    pass

from integrations import linkyar_client as ly


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else '@linktest'
    text = sys.argv[2] if len(sys.argv) > 2 else 'تست لینک‌یار'

    print('token len', len(ly.user_token() or ''))
    me = ly.get_me()
    print('get_me', me.get('ok'), 'user_id=', me.get('user_id'))

    r = ly.resolve_channel(target)
    print('resolve', r)

    # full admin diagnostic via internal async
    from integrations.linkyar_client import _run, _with_client, _resolve_peer

    async def diag(client):
        resolved = await _resolve_peer(client, target)
        print('resolved detail', resolved)
        if not resolved.get('ok'):
            return resolved
        pid = int(resolved['peer_id'])
        try:
            joined = await client.join_public_chat(pid)
            print('join', joined)
        except Exception as e:
            print('join err', type(e).__name__, e)
        try:
            perms = await client.get_member_permissions(pid, client.id)
            print('permissions', perms.model_dump() if hasattr(perms, 'model_dump') else perms)
        except Exception as e:
            print('perms err', type(e).__name__, e)
        return await ly.send_text_to_channel.__wrapped__ if False else None

    # send via public API (includes access_hash path)
    sent = ly.send_text_to_channel(target, text)
    print('send', sent)


if __name__ == '__main__':
    main()
