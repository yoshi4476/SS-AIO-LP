# -*- coding: utf-8 -*-
"""補助金サイト（lp.7senses.co.jp）のフォームにロボットよけ（Cloudflare Turnstile）を付ける（2026-10-10 運用者の承認）。

補助金のページはブラウザから管制塔の Apps Script へ直接送る（合言葉を持てない）。機械で大量に送られると台帳が埋まり、
管制塔の自動返信で他人のアドレスへ当社のメールを出させられる。管制塔（contact.hub.gs の botCheck_）が、
ここで添えた答え（cf-turnstile-response）を Cloudflare に確かめる。断るかは管制塔の TURNSTILE_ENFORCE が決める。

ページへ足すのは2つ:
  1. 共通の部品 <script id="ss-turnstile-js">（何度当てても同じ。中身を直したらここを直せば全ページが揃う）
  2. 送り口 fetch(GAS_ENDPOINT, …) を ssTs.send(GAS_ENDPOINT, payload) に替える（部品が無ければ従来どおり送る）

部品は約590KBあるので、フォームに触れた時点で読む（開いた時点では読まない。表示速度の方針）。見た目は interaction-only。
送る直前に答えが無ければ最大6秒待ち、無くても送る（部品が読めない人の問い合わせを、ページの側で止めない）。

subsidy/pages.py の sync_chrome が毎回の配信で当てる。手で当てるとき:
    python scripts/subsidy/turnstile_block.py [<補助金の作業コピー>]
"""
import re
import sys
from pathlib import Path

# サイトキーは公開してよい値（ページに載る）。秘密鍵は管制塔の Apps Script だけが持つ
SITEKEY = "0x4AAAAAAFNDzhowC4hFfwIZ"

BLOCK = """<script id="ss-turnstile-js">
/* ロボットよけ（Cloudflare Turnstile。管制塔の scripts/subsidy/turnstile_block.py が揃える）。フォームに触れた時点で部品を読み、
   送る直前に答えを添える（最大6秒待ち、無くても送る。断るかは管制塔が決める）。見た目は interaction-only */
window.ssTs=(function(){
var KEY="__KEY__",SCOPE="#contactForm,#svcForm,#unsubForm,#diagBody",HIDE="position:absolute;width:0;height:0;overflow:hidden";
var ready=null,last=null;
function load(){
 if(ready)return ready;
 ready=new Promise(function(done){
  if(window.turnstile)return done(window.turnstile);
  window.ssTsReady=function(){done(window.turnstile||null);};
  var s=document.createElement("script");
  s.src="https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit&onload=ssTsReady";
  s.async=true;s.onerror=function(){done(null);};
  document.head.appendChild(s);
 });
 return ready;
}
function btnOf(sc){return sc.querySelector('button[type="submit"],#d-show');}
function mount(sc){
 var st=sc._ts;
 if(st&&(!st.box||st.box.isConnected))return;
 st=sc._ts={state:"wait",box:null,id:null};
 load().then(function(ts){
  var b=btnOf(sc);
  if(!ts||!sc.isConnected||!b){st.state="off";return;}
  var box=document.createElement("div");
  box.className="ts-box";box.style.cssText=HIDE;
  b.parentNode.insertBefore(box,b);
  st.box=box;st.state="run";
  try{
   st.id=ts.render(box,{sitekey:KEY,appearance:"interaction-only",language:"ja",action:"subsidy",
    callback:function(){st.state="ok";},
    "expired-callback":function(){st.state="run";},
    "error-callback":function(){st.state="err";},
    "before-interactive-callback":function(){st.state="ask";box.style.cssText="margin:8px 0";}});
  }catch(e){st.state="off";}
 });
}
function touch(e){
 var sc=e.target&&e.target.closest?e.target.closest(SCOPE):null;
 if(!sc||(sc.id==="diagBody"&&!sc.querySelector("#d-show")))return;
 last=sc;mount(sc);
}
document.addEventListener("focusin",touch,true);
document.addEventListener("pointerdown",touch,true);
function tok(st){var i=st&&st.box&&st.box.querySelector('input[name="cf-turnstile-response"]');return i?i.value:"";}
function token(){
 var st=last&&last._ts,t0=Date.now();
 return new Promise(function(done){
  (function poll(){
   var t=tok(st);
   if(t||!st||!st.box&&st.state!=="wait"||(st.state!=="wait"&&st.state!=="run"&&st.state!=="ask")||Date.now()-t0>6000)return done(t);
   setTimeout(poll,150);
  })();
 });
}
function renew(st){try{if(st&&st.id!=null&&window.turnstile){window.turnstile.reset(st.id);st.state="run";}}catch(e){}}
return {send:function(url,payload){
 var st=last&&last._ts;
 return token().catch(function(){return "";}).then(function(t){
  var b=t?Object.assign({"cf-turnstile-response":t},payload):payload;
  var p=fetch(url,{method:"POST",headers:{"Content-Type":"text/plain;charset=utf-8"},body:JSON.stringify(b)});
  p.then(function(){renew(st);},function(){renew(st);});
  return p;
 });
}};
})();
</script>""".replace("__KEY__", SITEKEY)

BLOCK_RX = re.compile(r'<script id="ss-turnstile-js">.*?</script>', re.S)
# ページの送り口。部品が無い（読めなかった）ときは従来どおり送る
SEND_OLD = 'fetch(GAS_ENDPOINT,{method:"POST",headers:{"Content-Type":"text/plain;charset=utf-8"},body:JSON.stringify(payload)})'
SEND_NEW = ('(window.ssTs?ssTs.send(GAS_ENDPOINT,payload):fetch(GAS_ENDPOINT,{method:"POST",'
            'headers:{"Content-Type":"text/plain;charset=utf-8"},body:JSON.stringify(payload)}))')


def apply(text):
    """管制塔へ直接送るページ（GAS_ENDPOINT を持つ）にだけ当てる。何度当てても同じ結果"""
    if "const GAS_ENDPOINT" not in text or "</body>" not in text:
        return text
    nl = "\r\n" if "\r\n" in text else "\n"
    block = BLOCK.replace("\n", nl)
    u = text.replace(SEND_OLD, SEND_NEW) if SEND_NEW not in text else text
    if BLOCK_RX.search(u):
        u = BLOCK_RX.sub(lambda _: block, u, count=1)
    else:
        u = u.replace("</body>", block + nl + "</body>", 1)
    return u


def unsent(text):
    """管制塔へ直接送るのに、答えを添える送り口になっていない箇所の数（門・検査用）"""
    if "const GAS_ENDPOINT" not in text:
        return 0
    return len(re.findall(r"fetch\(GAS_ENDPOINT", text)) - text.count("ssTs.send(GAS_ENDPOINT")


SKIP = {".git", "node_modules", "dist", "blog-system", "automation", "reports"}


def apply_all(root):
    n = []
    for p in sorted(Path(root).rglob("*.html")):
        if SKIP & set(p.relative_to(root).parts):
            continue
        t = p.read_bytes().decode("utf-8", "surrogateescape")
        u = apply(t)
        if u != t:
            p.write_bytes(u.encode("utf-8", "surrogateescape"))
            n.append(p.relative_to(root).as_posix())
    return n


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / ".publish-work" / "subsidy"
    done = apply_all(root)
    print(f"ロボットよけ: {len(done)}ページに当てました" + (f"（{', '.join(done)}）" if done else ""))
