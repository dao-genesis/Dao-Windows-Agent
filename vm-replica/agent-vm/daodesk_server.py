# -*- coding: utf-8 -*-
"""daodesk_server.py -- 分身桌面可视面板(Windows 原生·零依赖·归一单网页子页)。

定位:在 guacd/Docker 不可用的用户真机环境下的实用可视路线——把每路分身会话的
画面(会话内 GDI 捕获)与键鼠输入路由进归一单网页(VS Code Webview 内的 /shell 子页)。
原生远程桌面协议级路由(desktop/tunnel 路线A)仍是长期主形态;本面板是控制面配套的
帧级监视/操作面板,与 vm_host_daemon(:9000) 直接对接,纯标准库,一个文件即起。

用法(在宿主 Windows 上):
  C:\\dao_vm\\python\\python.exe daodesk_server.py   # 127.0.0.1:9200
  然后在归一单网页里 browser_shell_tab open http://127.0.0.1:9200
代理动作:
  - 帧   : {action: vm.screenshot}  (逐会话隔离画面)
  - 输入 : vm.click / vm.mouse_move / vm.double_click / vm.right_click /
           vm.scroll / vm.type / vm.key  (点击某桌面=激活该分身接管键鼠)
"""
import base64, json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import request as urlreq, parse as urlparse

CFG_PATH = r"C:\ProgramData\dao_vm\config.json"
HOST_URL = "http://127.0.0.1:9000/"
BIND = ("127.0.0.1", 9200)
_size_cache = {}
_token = None

def token():
    global _token
    if _token is None:
        _token = json.load(open(CFG_PATH, "r", encoding="utf-8-sig"))["token"]
    return _token

def daemon(action, **kw):
    body = dict(kw); body["action"] = action
    data = json.dumps(body).encode("utf-8")
    req = urlreq.Request(HOST_URL, data=data, method="POST",
                         headers={"Authorization": "Bearer " + token(),
                                  "Content-Type": "application/json"})
    with urlreq.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

def vm_size(vm):
    s = _size_cache.get(vm)
    if not s:
        d = daemon("vm.desktop_info", vm=vm)
        s = (int(d.get("width", 1280)), int(d.get("height", 800)))
        _size_cache[vm] = s
    return s

KEYMAP = {"Enter": "enter", "Backspace": "backspace", "Tab": "tab", "Escape": "esc",
          "Delete": "delete", "ArrowUp": "up", "ArrowDown": "down", "ArrowLeft": "left",
          "ArrowRight": "right", "Home": "home", "End": "end", "PageUp": "pageup",
          "PageDown": "pagedown", " ": "space"}

PAGE = r"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>DAO 多分身桌面 · 单网页内多RDP(Windows 原生)</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%;font-family:system-ui,sans-serif;background:#0e0e12;color:#ddd}
#bar{height:34px;display:flex;align-items:center;gap:10px;padding:0 10px;background:#1b1b22;border-bottom:1px solid #2c2c36;font-size:13px}
#bar b{color:#6cc0ff}
#bar .sp{opacity:.55}
#grid{position:absolute;top:34px;left:0;right:0;bottom:0;display:flex;gap:2px;background:#000}
.pane{flex:1;min-width:0;display:flex;flex-direction:column;border:2px solid transparent}
.pane.active{border-color:#3c8dbc}
.pane .hd{height:24px;display:flex;justify-content:space-between;align-items:center;padding:0 8px;background:#23232c;font-size:12px}
.pane .hd .st{opacity:.7}
.pane .vp{flex:1;position:relative;overflow:hidden;background:#000;display:flex;align-items:center;justify-content:center}
.pane img{max-width:100%;max-height:100%;display:block;image-rendering:auto}
.pane .ov{position:absolute;inset:0;cursor:crosshair;outline:none}
</style></head><body>
<div id="bar"><b>☯ DAO 多分身桌面</b><span class="sp">单网页内 · Windows 原生多RDP · 帧+输入路由到选中分身</span>
<span class="sp">| 点击某桌面=激活它接管键鼠 |</span><span id="fps" class="sp"></span></div>
<div id="grid"></div>
<script>
let active=null; const panes={};
async function j(u,o){const r=await fetch(u,o);return r.json();}
function mkpane(vm,label){
  const d=document.createElement('div');d.className='pane';d.id='p-'+vm;
  d.innerHTML='<div class="hd"><span>分身 <b>'+vm+'</b> · '+label+'</span><span class="st" id="st-'+vm+'">连接中…</span></div>'+
    '<div class="vp"><img id="im-'+vm+'"><div class="ov" id="ov-'+vm+'" tabindex="0"></div></div>';
  document.getElementById('grid').appendChild(d);
  panes[vm]={img:d.querySelector('#im-'+vm),ov:d.querySelector('#ov-'+vm),st:d.querySelector('#st-'+vm),busy:false,lastMove:0};
  wire(vm); loop(vm);
}
function setActive(vm){active=vm;for(const k in panes)document.getElementById('p-'+k).classList.toggle('active',k===vm);panes[vm].ov.focus();}
function norm(vm,e){const im=panes[vm].img;const r=im.getBoundingClientRect();
  let nx=(e.clientX-r.left)/r.width,ny=(e.clientY-r.top)/r.height;
  nx=Math.max(0,Math.min(1,nx));ny=Math.max(0,Math.min(1,ny));return {nx,ny};}
async function inp(vm,p){p.vm=vm;try{await fetch('/input',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});}catch(e){}}
function wire(vm){const p=panes[vm];const ov=p.ov;
  ov.addEventListener('mousedown',e=>{e.preventDefault();setActive(vm);const {nx,ny}=norm(vm,e);inp(vm,{type:'click',nx,ny,button:e.button});});
  ov.addEventListener('contextmenu',e=>e.preventDefault());
  ov.addEventListener('mousemove',e=>{const now=Date.now();if(now-p.lastMove<90)return;p.lastMove=now;const {nx,ny}=norm(vm,e);inp(vm,{type:'move',nx,ny});});
  ov.addEventListener('dblclick',e=>{const {nx,ny}=norm(vm,e);inp(vm,{type:'dblclick',nx,ny});});
  ov.addEventListener('wheel',e=>{e.preventDefault();const {nx,ny}=norm(vm,e);inp(vm,{type:'scroll',nx,ny,dy:e.deltaY});},{passive:false});
  ov.addEventListener('keydown',e=>{e.preventDefault();
    const mods=[];if(e.ctrlKey)mods.push('ctrl');if(e.altKey)mods.push('alt');if(e.shiftKey&&e.key.length>1)mods.push('shift');
    let named=null; if(e.key in {Enter:1,Backspace:1,Tab:1,Escape:1,Delete:1,ArrowUp:1,ArrowDown:1,ArrowLeft:1,ArrowRight:1,Home:1,End:1,PageUp:1,PageDown:1})named=e.key;
    if(mods.length&&e.key.length===1){inp(vm,{type:'combo',key:mods.concat([e.key.toLowerCase()]).join('+')});}
    else if(named){inp(vm,{type:'named',key:mods.concat([named]).join('+')});}
    else if(e.key.length===1&&!e.ctrlKey&&!e.altKey){inp(vm,{type:'text',text:e.key});}
  });
}
function loop(vm){const p=panes[vm];
  function next(){const im=p.img;im.onload=()=>{p.st.textContent='● 实时';p.st.style.color='#7fdc7f';setTimeout(next,250);};
    im.onerror=()=>{p.st.textContent='帧错误·重试';p.st.style.color='#e0a030';setTimeout(next,800);};
    im.src='/frame?vm='+encodeURIComponent(vm)+'&t='+Date.now();}
  next();
}
(async()=>{try{const d=await j('/vms');const vms=d.vms||{};const ks=Object.keys(vms);
  if(!ks.length){document.getElementById('grid').innerHTML='<div style="margin:auto;opacity:.6">无运行中的分身(vm)</div>';return;}
  ks.forEach(k=>mkpane(k,(vms[k].session_user||k)));setActive(ks[0]);
}catch(e){document.getElementById('grid').innerHTML='<div style="margin:auto;color:#e66">加载失败: '+e+'</div>';}})();
</script></body></html>"""

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, ctype, body, extra=None):
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        if extra:
            for k, v in extra.items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        u = urlparse.urlparse(self.path); q = urlparse.parse_qs(u.query)
        try:
            if u.path == "/" or u.path == "/index.html":
                self._send(200, "text/html; charset=utf-8", PAGE.encode("utf-8")); return
            if u.path == "/vms":
                self._send(200, "application/json", json.dumps(daemon("vm.list")).encode("utf-8")); return
            if u.path == "/size":
                w, h = vm_size(q["vm"][0]); self._send(200, "application/json", json.dumps({"width": w, "height": h}).encode()); return
            if u.path == "/frame":
                vm = q["vm"][0]; r = daemon("vm.screenshot", vm=vm, format="png")
                img = base64.b64decode(r.get("image_base64", ""))
                self._send(200, "image/png", img); return
            self._send(404, "text/plain", b"nf")
        except Exception as e:
            self._send(502, "text/plain", ("err: %s" % e).encode())

    def do_POST(self):
        if urlparse.urlparse(self.path).path != "/input":
            self._send(404, "text/plain", b"nf"); return
        try:
            n = int(self.headers.get("Content-Length", 0))
            p = json.loads(self.rfile.read(n).decode("utf-8"))
            vm = p["vm"]; t = p.get("type")
            if t in ("click", "move", "dblclick", "scroll"):
                w, h = vm_size(vm); x = int(p.get("nx", 0) * w); y = int(p.get("ny", 0) * h)
                if t == "move":
                    daemon("vm.mouse_move", vm=vm, x=x, y=y)
                elif t == "dblclick":
                    daemon("vm.double_click", vm=vm, x=x, y=y)
                elif t == "scroll":
                    daemon("vm.scroll", vm=vm, x=x, y=y, clicks=(-3 if p.get("dy", 0) > 0 else 3))
                else:
                    if p.get("button") == 2:
                        daemon("vm.right_click", vm=vm, x=x, y=y)
                    else:
                        daemon("vm.click", vm=vm, x=x, y=y)
            elif t == "text":
                daemon("vm.type", vm=vm, text=p.get("text", ""))
            elif t in ("named", "combo"):
                daemon("vm.key", vm=vm, key=p.get("key", ""))
            self._send(200, "application/json", b'{"ok":true}')
        except Exception as e:
            self._send(502, "application/json", json.dumps({"ok": False, "err": str(e)}).encode())

if __name__ == "__main__":
    print("daodesk_server on http://%s:%d" % BIND, flush=True)
    ThreadingHTTPServer(BIND, H).serve_forever()
