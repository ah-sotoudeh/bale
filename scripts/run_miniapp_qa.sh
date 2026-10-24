#!/usr/bin/env bash
# عیب‌یابی هوشمند برگه‌های مینی‌اپ
set -e
cd "$(dirname "$0")/.."
node scripts/miniapp_page_qa.js "$@"
