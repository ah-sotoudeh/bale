#!/usr/bin/env python3
"""Apply mini-app UI + role fixes to miniapp/static/*/index.html on the server."""
from pathlib import Path

paths = [
    Path('miniapp/static/app/index.html'),
    Path('miniapp/static/manager/index.html'),
]

for p in paths:
    if not p.exists():
        print('skip missing', p)
        continue
    html = p.read_text(encoding='utf-8')
    if 'rolebar' in html and 'max-width:430px' in html:
        print('already updated', p)
        continue

    needle = '      -webkit-font-smoothing:antialiased;\n    }'
    inject = '''      -webkit-font-smoothing:antialiased;
    }
    @media (min-width: 480px){
      body{background:#0b0d10;display:flex;justify-content:center;align-items:flex-start;min-height:100dvh;padding:16px 12px 24px}
      #app{width:100%;max-width:430px;min-height:min(900px,100dvh);border-radius:20px;border:1px solid var(--sep);overflow:hidden;box-shadow:0 12px 40px rgba(0,0,0,.35);background:var(--bg)}
      nav.tabs{max-width:430px;left:50%;transform:translateX(-50%);border-radius:0 0 20px 20px}
      .toast{max-width:398px;left:50%;right:auto;transform:translateX(-50%)}
    }
    .rolebar{display:flex;gap:6px;padding:0 12px 10px;flex-wrap:wrap;justify-content:center}
    .rolebar button{min-height:36px;border:0;border-radius:999px;padding:0 12px;font-size:12px;font-weight:600;background:transparent;color:var(--hint)}
    .rolebar button.on{background:var(--link);color:#fff}
    .guide{margin-bottom:12px}
    .guide h2{margin:0 0 6px;font-size:11px;color:var(--hint);font-weight:600}
    .guide ol{list-style:none;margin:0;padding:0;background:var(--sec);border-radius:16px;border:1px solid var(--sep);overflow:hidden}
    .guide li{display:flex;gap:8px;padding:10px 12px;border-bottom:1px solid var(--sep);font-size:12px;line-height:1.5}
    .guide li:last-child{border-bottom:0}
    .guide .n{flex:0 0 20px;height:20px;border-radius:999px;background:color-mix(in srgb,var(--link) 20%,transparent);color:var(--link);font-size:11px;font-weight:700;display:grid;place-items:center}
    .menu{background:var(--sec);border:1px solid var(--sep);border-radius:16px;overflow:hidden;margin-bottom:10px}
    .menu button{display:flex;width:100%;text-align:right;gap:8px;align-items:center;border:0;border-bottom:1px solid var(--sep);background:none;color:inherit;padding:12px}
    .menu button:last-child{border-bottom:0}
    .menu .t{flex:1;min-width:0}
    .menu .t b{display:block;font-size:13px}
    .menu .t span{display:block;font-size:11px;color:var(--hint);margin-top:2px}'''
    if needle not in html:
        print('css needle missing', p)
        continue
    html = html.replace(needle, inject, 1)

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
    if old not in html:
        print('boot needle missing', p)
    else:
        html = html.replace(old, new, 1)

    if 'function roleBar()' not in html:
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
            print('render needle missing', p)
        else:
            new_r = (
                "    function roleBar(){\n"
                "      const caps=(me&&me.caps)||{customer:true,manager:false,operator:false};\n"
                "      const items=[];\n"
                "      if(caps.manager || role==='manager') items.push(['manager','مدیر']);\n"
                "      items.push(['customer','مشتری']);\n"
                "      if(caps.operator) items.push(['operator','پشتیبانی']);\n"
                "      if(items.length<2) return '';\n"
                "      return `<div class=\"rolebar\">${items.map(([id,l])=>`<button type=\"button\" data-role=\"${id}\" class=\"${role===id?'on':''}\">${l}</button>`).join('')}</div>`;\n"
                "    }\n\n"
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
            html = html.replace(old_r, new_r, 1)

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
    if old_b in html and "data-role]').forEach" not in html:
        html = html.replace(old_b, new_b, 1)

    p.write_text(html, encoding='utf-8')
    print('updated', p)

print('done')
