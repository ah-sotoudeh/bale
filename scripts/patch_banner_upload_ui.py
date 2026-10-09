#!/usr/bin/env python3
"""Enable mini-app banner upload in built panel JS (idempotent)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "miniapp" / "static" / "panel" / "assets" / "index-Ce1t18yS.js"


def main() -> None:
    if not JS.is_file():
        raise SystemExit(f"missing {JS}")
    js = JS.read_text(encoding="utf-8", errors="ignore")
    if "/banners/create" in js and "__lbLastBannerFile" in js:
        print("already patched")
        return

    old = "submitBanner:n=>{if(nA())return `بنر جدید از بازو و کانال بنرها ثبت می\u200cشود.`;"
    new = (
        "submitBanner:n=>{if(nA())return(async()=>{{"
        "try{{"
        "const f=window.__lbLastBannerFile;"
        "if(!f)return`تصویر یا ویدیو را انتخاب کنید`;"
        "const cap=String(n.caption||``).trim();"
        "const title=(String(n.title||``).trim()||cap.split(`\\n`)[0]||``).slice(0,80);"
        "if(cap.length<12)return C().error.captionShort;"
        "const buf=await f.arrayBuffer();"
        "const bytes=new Uint8Array(buf);"
        "let bin=``;for(let i=0;i<bytes.length;i++)bin+=String.fromCharCode(bytes[i]);"
        "const b64=btoa(bin);"
        "const data=await iA(`/banners/create`,{title,caption:cap,media_kind:n.mediaKind||`photo`,media_base64:b64,filename:f.name||`banner.bin`});"
        "const id=Number(data.banner_id)||Date.now();"
        "const mediaUrl=String(data.media_url||``);"
        "const st=t();"
        "e({banners:[{id,title:String(data.title||title),caption:cap,fromLinkbank:!1,mediaKind:n.mediaKind||`photo`,mediaUrl,posterUrl:n.mediaKind===`video`?``:mediaUrl,stage:String(data.stage||`pending`),rejectReason:``},...st.banners]});"
        "return null;"
        "}catch(err){return String((err&&err.message)||`ثبت بنر انجام نشد`)}"
        "})();"
    )
    if old not in js:
        # try without ZWNJ
        old2 = "submitBanner:n=>{if(nA())return `بنر جدید از بازو و کانال بنرها ثبت می‌شود.`;"
        if old2 not in js:
            raise SystemExit("submitBanner live branch not found — panel JS may have changed")
        old = old2
    js = js.replace(old, new, 1)

    old_h = "function h(t){if(!t){y(``);return}let n=URL.createObjectURL(t);"
    new_h = "function h(t){if(!t){y(``);window.__lbLastBannerFile=null;return}window.__lbLastBannerFile=t;let n=URL.createObjectURL(t);"
    if old_h in js:
        js = js.replace(old_h, new_h, 1)

    old_samples = (
        "(0,Q.jsx)(`div`,{className:`mb-2 grid grid-cols-2 gap-2`,children:Lj.map(e=>(0,Q.jsx)(`button`,{"
        "type:`button`,className:`min-h-11 rounded-xl border px-3 text-xs ${d===e.mediaUrl?`border-link text-link`:`border-line text-muted`}`,"
        "onClick:()=>{u(e.mediaKind),f(e.mediaUrl),m(e.posterUrl),y(``)},children:e.label},e.label))}),"
    )
    if old_samples in js:
        js = js.replace(old_samples, "", 1)

    old_lead = "children:[C().banner.composerLead,i?w(C().tpl.feeCost,{fee:X(i)}):C().tpl.firstFree,` `,C().banner.composerBack]"
    new_lead = "children:[C().banner.composerLead,` `,C().banner.composerBack]"
    if old_lead in js:
        js = js.replace(old_lead, new_lead, 1)

    old_click = (
        "onClick:()=>{let t=n({title:a,caption:s,mediaKind:l,mediaUrl:d,posterUrl:p});"
        "t||r(),$(e,i?C().toast.sentPaid:C().toast.sentFree,t)},"
        "children:i?w(C().tpl.sendPaid,{fee:X(i)}):C().tpl.sendFree"
    )
    new_click = (
        "onClick:()=>{Promise.resolve(n({title:a,caption:s,mediaKind:l,mediaUrl:d,posterUrl:p}))"
        ".then(t=>{t||r(),$(e,C().toast.sentFree,t)})},children:C().tpl.sendFree"
    )
    if old_click in js:
        js = js.replace(old_click, new_click, 1)

    JS.write_text(js, encoding="utf-8")
    print("patched", JS)


if __name__ == "__main__":
    main()
