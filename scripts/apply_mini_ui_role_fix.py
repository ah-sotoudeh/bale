#!/usr/bin/env python3
"""Fix mini-app static UI: role switcher, no max-width frame (Bale iframe owns size)."""
from __future__ import annotations

import re
from pathlib import Path

paths = [
    Path('miniapp/static/app/index.html'),
    Path('miniapp/static/manager/index.html'),
]


def strip_phone_frame(html: str) -> str:
    html = re.sub(r'/\*\s*قاب موبایل.*?\*/\s*', '', html, count=1, flags=re.S)
    html = re.sub(
        r'@media\s*\(min-width:\s*480px\)\s*\{(?:[^{}]|\{[^{}]*\})*max-width:\s*430px;(?:[^{}]|\{[^{}]*\})*\}',
        '',
        html,
        count=1,
        flags=re.S,
    )
    html = html.replace('max-width:430px', 'max-width:none')
    html = html.replace('background:#0b0d10;', '')
    return html


def ensure_fill(html: str) -> str:
    html = html.replace(
        'html,body{margin:0;min-height:100%}',
        'html,body{margin:0;height:100%;min-height:100%}',
        1,
    )
    html = html.replace(
        '#app{display:flex;flex-direction:column;min-height:100dvh}',
        '#app{display:flex;flex-direction:column;min-height:100%;height:100%;width:100%}',
        1,
    )
    return html


def ensure_role_css(html: str) -> str:
    if '.rolebar{' in html:
        return html
    css = '''
    .rolebar{display:flex;gap:6px;padding:0 12px 10px;flex-wrap:wrap;justify-content:center}
    .rolebar button{min-height:36px;border:0;border-radius:999px;padding:0 12px;font-size:12px;font-weight:600;background:transparent;color:var(--hint)}
    .rolebar button.on{background:var(--link);color:#fff}
'''
    return html.replace(
        '    h3{margin:0 0 6px;font-size:14px}\n  </style>',
        '    h3{margin:0 0 6px;font-size:14px}\n' + css + '  </style>',
        1,
    )


def ensure_boot(html: str) -> str:
    old = (
        "        me=await api('/me');\n"
        "        role=me.is_operator?'operator':(me.channel_count>0?'manager':'customer');\n"
        "        const q=new URLSearchParams(location.search).get('role');\n"
        "        if(q==='customer'||q==='manager'||q==='operator') role=q;"
    )
    new = (
        "        me=await api('/me');\n"
        "        const caps={operator:!!me.is_operator,manager:!!(me.channel_count>0||me.can_be_manager),customer:true};\n"
        "        me.caps=caps;\n"
        "        const q=new URLSearchParams(location.search).get('role');\n"
        "        const saved=(localStorage.getItem('lb_role')||'');\n"
        "        let pick=q||saved||'';\n"
        "        if(pick==='operator' && !caps.operator) pick='';\n"
        "        if(q==='manager'){ role='manager'; }\n"
        "        else if(pick==='operator'||pick==='manager'||pick==='customer') role=pick;\n"
        "        else role=caps.operator?'operator':(caps.manager?'manager':'customer');\n"
        "        localStorage.setItem('lb_role', role);"
    )
    if old in html:
        html = html.replace(old, new, 1)
    return html


def ensure_rolebar_render(html: str) -> str:
    if 'function roleBar()' in html:
        return html
    old_r = None
    for arrow in ['\u279c', '\u2192', '➜', '→']:
        trial = (
            "    async function render(){\n"
            "      const app=document.getElementById('app');\n"
            "      const t=tabs();\n"
            "      app.innerHTML=`<header>\n"
            f"        ${{stack.length>1?'<button class=\"icon\" id=\"back\" aria-label=\"بازگشت\">{arrow}</button>':''}}\n"
            "        <div class=\"t\"><h1>${esc(title())}</h1><div class=\"sub\">${esc((me&&me.user&&(me.user.handle||me.user.bale_user_id))||'…')}</div></div>\n"
            "      </header>\n"
            "      <main id=\"view\"><div class=\"empty\">…</div></main>"
        )
        if trial in html:
            old_r = trial
            break
    if not old_r:
        return html
    new_r = (
        "    function roleBar(){\n"
        "      const caps=(me&&me.caps)||{customer:true,manager:false,operator:false};\n"
        "      const items=[];\n"
        "      if(caps.manager || role==='manager') items.push(['manager','مدیر']);\n"
        "      items.push(['customer','مشتری']);\n"
        "      if(caps.operator) items.push(['operator','پشتیبانی']);\n"
        "      if(items.length<2) return '';\n"
        "      return `<div class=\"rolebar\">${items.map(([id,l])=>`<button type=\"button\" data-role=\"${id}\" class=\"${role===id?'on':''}\">${l}</button>`).join('')}</div>`;\n"
        "    }\n"
        "    async function render(){\n"
        "      const app=document.getElementById('app');\n"
        "      const t=tabs();\n"
        "      app.innerHTML=`<header>\n"
        "        ${stack.length>1?'<button class=\"icon\" id=\"back\" aria-label=\"بازگشت\">→</button>':'<span class=\"icon\"></span>'}\n"
        "        <div class=\"t\"><h1>${esc(title())}</h1><div class=\"sub\">${esc((me&&me.user&&(me.user.handle||me.user.bale_user_id))||'…')}</div></div>\n"
        "        <span class=\"icon\"></span>\n"
        "      </header>\n"
        "      ${roleBar()}\n"
        "      <main id=\"view\"><div class=\"empty\">…</div></main>"
    )
    return html.replace(old_r, new_r, 1)


def ensure_bind(html: str) -> str:
    if "data-role]').forEach" in html:
        return html
    old_b = "      if(backBtn) backBtn.onclick=back;\n      document.querySelectorAll('[data-go]')"
    new_b = (
        "      if(backBtn) backBtn.onclick=back;\n"
        "      document.querySelectorAll('[data-role]').forEach(b=>b.onclick=()=>{\n"
        "        const r=b.getAttribute('data-role');\n"
        "        if(r==='manager'||r==='customer'||r==='operator'){\n"
        "          role=r; localStorage.setItem('lb_role', r); stack=[{name:'home'}]; render();\n"
        "        }\n"
        "      });\n"
        "      document.querySelectorAll('[data-go]')"
    )
    if old_b in html:
        html = html.replace(old_b, new_b, 1)
    return html


for p in paths:
    if not p.exists():
        print('skip missing', p)
        continue
    html = p.read_text(encoding='utf-8')
    html = strip_phone_frame(html)
    html = ensure_fill(html)
    html = ensure_role_css(html)
    html = ensure_boot(html)
    html = ensure_rolebar_render(html)
    html = ensure_bind(html)
    p.write_text(html, encoding='utf-8')
    print('updated', p)

print('done')
