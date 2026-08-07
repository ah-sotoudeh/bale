#!/usr/bin/env python3
"""Small Flask listener for Bale webhooks used in CI E2E test.
Receives incoming updates from Bale and replies back with a simple acknowledgement
using the Bale Bot API (sendMessage).

Endpoint: POST /bale/webhook

Environment variables required:
- BALE_BOT_TOKEN

This script is intentionally minimal for CI testing only.
"""
import os
import sys
import json
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)
BALE_TOKEN = os.environ.get('BALE_BOT_TOKEN')
if not BALE_TOKEN:
    print('BALE_BOT_TOKEN is not set', file=sys.stderr)

BALE_API_BASE = os.environ.get('BALE_API_URL', 'https://tapi.bale.ai')


def send_message(chat_id, text):
    if not BALE_TOKEN:
        print('No BALE_TOKEN; cannot send message', file=sys.stderr)
        return None
    url = f"{BALE_API_BASE}/bot{BALE_TOKEN}/sendMessage"
    payload = {'chat_id': chat_id, 'text': text}
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print('Failed to send message:', e, file=sys.stderr)
        return None


@app.route('/bale/webhook', methods=['POST'])
def bale_webhook():
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({'ok': False, 'error': 'invalid json'}), 400

    # basic handlers: message and pre_checkout/successful_payment
    if 'message' in data:
        msg = data['message']
        chat = msg.get('chat', {})
        chat_id = chat.get('id') or chat.get('username')
        text = msg.get('text', '')
        reply = f"Auto-reply: I received your message: {text}"
        send_message(chat_id, reply)
        return jsonify({'ok': True})

    # handle successful_payment (just log for now)
    if 'successful_payment' in data:
        # process payment confirmation
        print('Payment webhook received:', data)
        return jsonify({'ok': True})

    # unknown
    print('Unhandled webhook payload:', json.dumps(data)[:200])
    return jsonify({'ok': True})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    # allow external connections for ngrok
    app.run(host='0.0.0.0', port=port)
