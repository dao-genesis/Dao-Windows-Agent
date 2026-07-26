"use strict";
// DAO Windows Agent · 独立总控主页（VS Code 独立宿主 · 真隔离）
//
// 本模块 = Windows Agent 自己的前端主页：官方 mstsc 五页配置台 + 账号池 + 开桌面，
// 全部承载在本插件自己的 webview（daoWinHome）里，不注入、不依赖 dao-one/归一插件。
// 归一插件（Devin Desktop）保持自身边界；确需归一宿主时经 daoWin.homeMode=dao-one 显式委派。
//
// 数据面：RDP 档案原语（rdpSave/rdpDelete/rdpLaunch/info）与账号池（桥 /api/account.*、
// 隧道 /accounts）均由宿主 extension.js 处理消息后回推，本文件只负责前端模板（headless 可测）。

const WRD_RES = [[640, 480], [800, 600], [1024, 768], [1280, 720], [1366, 768], [1600, 900], [1920, 1080], [2560, 1440]];

// 独立总控主页模板。state = { sessionId, platform, rdp:[], accounts:[], subplugins:[] }。
function winHomeHtml(state) {
  return `<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<style>
*{box-sizing:border-box}
body{font-family:var(--vscode-font-family);padding:10px 14px;color:var(--vscode-foreground);font-size:13px}
h2{margin:4px 0 2px} .sid{opacity:.7;font-size:12px;margin-bottom:8px}
.card{border:1px solid var(--vscode-panel-border);border-radius:6px;padding:8px 10px;margin:8px 0}
.st{font-weight:600;margin:8px 0 4px}
.cr{display:flex;align-items:center;gap:8px;margin:4px 0;flex-wrap:wrap}
.cr .l{min-width:170px;opacity:.85} .cr .v{flex:1;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
input,select{background:var(--vscode-input-background);color:var(--vscode-input-foreground);
  border:1px solid var(--vscode-input-border);border-radius:4px;padding:3px 6px}
button{padding:4px 10px;cursor:pointer;background:var(--vscode-button-background);
  color:var(--vscode-button-foreground);border:none;border-radius:4px}
button:hover{background:var(--vscode-button-hoverBackground)}
button.ghost{background:transparent;color:var(--vscode-foreground);border:1px solid var(--vscode-panel-border)}
.muted{opacity:.65;font-size:12px}
.row{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
table{border-collapse:collapse;width:100%} td,th{border-bottom:1px solid var(--vscode-panel-border);padding:4px 6px;text-align:left;font-size:12px}
.wtab{padding:2px 0}
/* 官方「远程桌面连接」对话框原样外壳（标题栏 + 页签条 + 页脚按钮行）。 */
.mstsc{max-width:560px;border:1px solid #6f6f6f;border-radius:2px;background:#f0f0f0;color:#000;margin:8px 0;box-shadow:0 2px 10px rgba(0,0,0,.35)}
.mstsc .titlebar{display:flex;align-items:center;gap:8px;background:linear-gradient(#fbfbfb,#e8e8e8);border-bottom:1px solid #d0d0d0;padding:8px 12px}
.mstsc .titlebar .ico{font-size:24px;line-height:1}
.mstsc .titlebar .tt{font-size:20px;color:#003399;font-weight:400}
.mstsc .tabbar{display:flex;gap:0;padding:8px 12px 0;background:#f0f0f0}
.mstsc .tabbar button{border:1px solid #a0a0a0;border-bottom:none;border-radius:4px 4px 0 0;background:#e1e1e1;color:#000;padding:4px 12px;margin-right:2px;font-size:12px}
.mstsc .tabbar button.sel{background:#f0f0f0;position:relative;top:1px;font-weight:600}
.mstsc .body{border-top:1px solid #a0a0a0;margin:0 12px;background:#f0f0f0;padding:8px 4px}
.mstsc .st{font-weight:600;margin:8px 4px 4px;color:#003399}
.mstsc .cr .l{color:#000;opacity:.95}
.mstsc input,.mstsc select{background:#fff;color:#000;border:1px solid #7a7a7a;border-radius:0;padding:2px 4px}
.mstsc .footer{display:flex;justify-content:flex-end;gap:8px;padding:10px 12px;border-top:1px solid #d0d0d0;background:#f0f0f0}
.mstsc .footer button{min-width:78px;background:#e1e1e1;color:#000;border:1px solid #8a8a8a;border-radius:3px;padding:4px 10px}
.mstsc .footer button.primary{background:#dceaffff;border-color:#3a7bd0;font-weight:600}
.mstsc .footer .spread{margin-right:auto;display:flex;gap:6px}
</style></head><body>
<h2>\u262f DAO Windows Agent \u00b7 \u72ec\u7acb\u603b\u63a7</h2>
<div class="sid">VS Code \u72ec\u7acb\u5bbf\u4e3b\uff08\u4e0d\u4f9d\u8d56\u5f52\u4e00\u63d2\u4ef6\uff09\u00b7 \u672c\u7a97\u53e3\u4f1a\u8bdd <b id="sid"></b> \u00b7 \u5b98\u65b9\u8fdc\u7a0b\u684c\u9762\u6a21\u5757\u524d\u7aef\u5316 + \u8d26\u53f7\u6c60</div>
<div class="row">
  <button id="mTabConfig" onclick="wmSwitch('config')">\u2460 \u7edf\u4e00\u914d\u7f6e\u7ba1\u7406\u53f0\uff08\u5b98\u65b9 mstsc \u4e94\u9875\uff09</button>
  <button id="mTabPool" class="ghost" onclick="wmSwitch('pool')">\u2461 \u8d26\u53f7\u6c60 \u00b7 \u591a\u8d26\u53f7\u7ba1\u7406</button>
  <button class="ghost" onclick="post({type:'openDesktop'})">\u5f00\u672c\u7a97\u53e3\u684c\u9762</button>
  <button class="ghost" onclick="post({type:'refresh'})">\u27f3 \u5237\u65b0</button>
</div>
<div id="main"></div>
<script>
const vscode = acquireVsCodeApi();
let STATE = ${JSON.stringify(state || {})};
const WRD_RES = ${JSON.stringify(WRD_RES)};
let WMOD = 'config';
let WEDIT = null; // null=列表; ''=新建; 名=编辑
let WTAB = 'general';
function post(m){ vscode.postMessage(m); }
function esc(s){ return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;'); }
document.getElementById('sid').textContent = STATE.sessionId || '';
function wmSwitch(m){ WMOD=(m==='pool')?'pool':'config'; render(); }

// ── 模块① 统一配置管理台：官方「远程桌面连接」五页（常规/显示/本地资源/体验/高级）──
function curProfile(){ let p={}; (STATE.rdp||[]).forEach(function(x){ if(x.name===WEDIT) p=x; }); return p; }
function wrForm(){
  const p = curProfile();
  const iv=(k,d)=>esc(p[k]!==undefined?p[k]:(d===undefined?'':d));
  const ck=(k,d)=>((p[k]!==undefined?p[k]:d)?' checked':'');
  const sl=(k,v,d)=>String(p[k]===undefined?d:p[k])===String(v)?' selected':'';
  const gcur=p.gwmethod!==undefined?p.gwmethod:(p.gateway?'manual':'auto');
  const gs=v=>gcur===v?' selected':'';
  let ri=WRD_RES.length;
  if(p.fullscreen===false){ ri=6; for(let i=0;i<WRD_RES.length;i++){ if(String(WRD_RES[i][0])===String(p.width)&&String(WRD_RES[i][1])===String(p.height)) ri=i; } }
  const resLabel=ri>=WRD_RES.length?'\u5168\u5c4f':(WRD_RES[ri][0]+' \u00d7 '+WRD_RES[ri][1]+' \u50cf\u7d20');
  let h='<div class="mstsc">';
  h+='<div class="titlebar"><span class="ico">\ud83d\udda5\ufe0f</span><span class="tt">\u8fdc\u7a0b\u684c\u9762\u8fde\u63a5</span></div>';
  h+='<div class="tabbar">'+[['general','\u5e38\u89c4'],['display','\u663e\u793a'],['local','\u672c\u5730\u8d44\u6e90'],['exp','\u4f53\u9a8c'],['adv','\u9ad8\u7ea7']].map(function(t){return '<button class="'+(WTAB===t[0]?'sel':'')+'" data-wtab="'+t[0]+'" onclick="wrTab(\\''+t[0]+'\\')">'+t[1]+'</button>';}).join('')+'</div>';
  h+='<div class="body">';
  h+='<div id="wtab_general" class="wtab"'+(WTAB==='general'?'':' style="display:none"')+'>';
  h+='<div class="st">\u767b\u5f55\u8bbe\u7f6e</div>';
  h+='<div class="cr"><span class="l">\u8ba1\u7b97\u673a(C)</span><span class="v"><input id="wf_host" placeholder="\u793a\u4f8b: computer.fabrikam.com" value="'+iv('host')+'"> : <input id="wf_port" size="5" placeholder="3389" value="'+iv('port')+'"></span></div>';
  h+='<div class="cr"><span class="l">\u7528\u6237\u540d</span><span class="v"><input id="wf_user" value="'+iv('username')+'"></span></div>';
  h+='<div class="cr"><span class="l"></span><span class="v muted">\u5f53\u4f60\u8fde\u63a5\u65f6\u5c06\u5411\u4f60\u8be2\u95ee\u51ed\u636e\u3002</span></div>';
  h+='<div class="cr"><span class="l"></span><span class="v"><label><input type="checkbox" id="wf_savecred"'+ck('savecred',false)+'>\u5141\u8bb8\u6211\u4fdd\u5b58\u51ed\u636e(R)</label></span></div>';
  h+='<div class="st">\u8fde\u63a5\u8bbe\u7f6e</div>';
  h+='<div class="cr"><span class="l">\u8fde\u63a5\u540d</span><span class="v"><input id="wf_name" placeholder="\u4fdd\u5b58\u7684\u8fde\u63a5\u540d(.rdp \u6587\u4ef6\u540d)" value="'+iv('name')+'"'+(WEDIT?' disabled':'')+'></span></div>';
  h+='</div>';
  h+='<div id="wtab_display" class="wtab"'+(WTAB==='display'?'':' style="display:none"')+'>';
  h+='<div class="st">\u663e\u793a\u914d\u7f6e</div>';
  h+='<div class="cr"><span class="l">\u9009\u62e9\u8fdc\u7a0b\u684c\u9762\u7684\u5927\u5c0f</span><span class="v">\u5c0f <input type="range" id="wf_res" min="0" max="'+WRD_RES.length+'" step="1" value="'+ri+'" oninput="wrRes(this)"> \u5927 \u00b7 <span id="wf_reslabel">'+resLabel+'</span></span></div>';
  h+='<div class="cr"><span class="l"></span><span class="v"><label><input type="checkbox" id="wf_multi"'+ck('multimon',false)+'>\u5c06\u6211\u7684\u6240\u6709\u76d1\u89c6\u5668\u7528\u4e8e\u8fdc\u7a0b\u4f1a\u8bdd(U)</label></span></div>';
  h+='<div class="st">\u989c\u8272</div>';
  h+='<div class="cr"><span class="l">\u9009\u62e9\u8fdc\u7a0b\u4f1a\u8bdd\u7684\u989c\u8272\u6df1\u5ea6(C)</span><span class="v"><select id="wf_bpp"><option value="15"'+sl('bpp',15,32)+'>\u589e\u5f3a\u8272(15 \u4f4d)</option><option value="16"'+sl('bpp',16,32)+'>\u589e\u5f3a\u8272(16 \u4f4d)</option><option value="24"'+sl('bpp',24,32)+'>\u771f\u5f69\u8272(24 \u4f4d)</option><option value="32"'+sl('bpp',32,32)+'>\u6700\u9ad8\u8d28\u91cf(32 \u4f4d)</option></select></span></div>';
  h+='<div class="cr"><span class="l"></span><span class="v"><label><input type="checkbox" id="wf_connbar"'+ck('connbar',true)+'>\u5168\u5c4f\u663e\u793a\u65f6\u663e\u793a\u8fde\u63a5\u680f(D)</label></span></div>';
  h+='</div>';
  h+='<div id="wtab_local" class="wtab"'+(WTAB==='local'?'':' style="display:none"')+'>';
  h+='<div class="st">\u8fdc\u7a0b\u97f3\u9891</div>';
  h+='<div class="cr"><span class="l">\u8fdc\u7a0b\u97f3\u9891\u64ad\u653e</span><span class="v"><select id="wf_audio"><option value="0"'+sl('audiomode',0,0)+'>\u5728\u6b64\u8ba1\u7b97\u673a\u4e0a\u64ad\u653e</option><option value="2"'+sl('audiomode',2,0)+'>\u4e0d\u64ad\u653e</option><option value="1"'+sl('audiomode',1,0)+'>\u5728\u8fdc\u7a0b\u8ba1\u7b97\u673a\u4e0a\u64ad\u653e</option></select></span></div>';
  h+='<div class="cr"><span class="l">\u8fdc\u7a0b\u97f3\u9891\u5f55\u5236</span><span class="v"><select id="wf_audiocap"><option value="0"'+sl('audiocapture',0,0)+'>\u4e0d\u8981\u5f55\u5236</option><option value="1"'+sl('audiocapture',1,0)+'>\u4ece\u6b64\u8ba1\u7b97\u673a\u5f55\u5236</option></select></span></div>';
  h+='<div class="st">\u952e\u76d8</div>';
  h+='<div class="cr"><span class="l">\u5e94\u7528 Windows \u7ec4\u5408\u952e(K)</span><span class="v"><select id="wf_kbd"><option value="2"'+sl('keyboardhook',2,2)+'>\u4ec5\u5728\u4f7f\u7528\u5168\u5c4f\u65f6</option><option value="0"'+sl('keyboardhook',0,2)+'>\u5728\u6b64\u8ba1\u7b97\u673a\u4e0a</option><option value="1"'+sl('keyboardhook',1,2)+'>\u5728\u8fdc\u7a0b\u8ba1\u7b97\u673a\u4e0a</option></select></span></div>';
  h+='<div class="st">\u672c\u5730\u8bbe\u5907\u548c\u8d44\u6e90</div>';
  h+='<div class="cr"><span class="l"></span><span class="v"><label><input type="checkbox" id="wf_prn"'+ck('printers',true)+'>\u6253\u5370\u673a(T)</label> <label><input type="checkbox" id="wf_clip"'+ck('clipboard',true)+'>\u526a\u8d34\u677f(L)</label></span></div>';
  h+='<div class="cr"><span class="l">\u8be6\u7ec6\u4fe1\u606f(M)</span><span class="v"><label><input type="checkbox" id="wf_smart"'+ck('smartcards',true)+'>\u667a\u80fd\u5361</label> <label><input type="checkbox" id="wf_ports"'+ck('ports',false)+'>\u7aef\u53e3</label> <label><input type="checkbox" id="wf_drv"'+ck('drives',false)+'>\u9a71\u52a8\u5668</label> <label><input type="checkbox" id="wf_pnp"'+ck('pnp',false)+'>\u5176\u4ed6\u652f\u6301\u7684\u5373\u63d2\u5373\u7528\u8bbe\u5907</label></span></div>';
  h+='</div>';
  h+='<div id="wtab_exp" class="wtab"'+(WTAB==='exp'?'':' style="display:none"')+'>';
  h+='<div class="st">\u6027\u80fd</div>';
  h+='<div class="cr"><span class="l">\u9009\u62e9\u8fde\u63a5\u901f\u5ea6\u6765\u4f18\u5316\u6027\u80fd(P)</span><span class="v"><select id="wf_conn"><option value="7"'+sl('conntype',7,7)+'>\u81ea\u52a8\u68c0\u6d4b\u8fde\u63a5\u8d28\u91cf(A)</option><option value="1"'+sl('conntype',1,7)+'>\u8c03\u5236\u89e3\u8c03\u5668(56 kbps)</option><option value="2"'+sl('conntype',2,7)+'>\u4f4e\u901f\u5bbd\u5e26(256 kbps - 2 Mbps)</option><option value="3"'+sl('conntype',3,7)+'>\u536b\u661f(2 Mbps - 16 Mbps, \u9ad8\u5ef6\u8fdf)</option><option value="4"'+sl('conntype',4,7)+'>\u9ad8\u901f\u5bbd\u5e26(2 Mbps - 10 Mbps)</option><option value="5"'+sl('conntype',5,7)+'>WAN(10 Mbps \u6216\u66f4\u9ad8, \u9ad8\u5ef6\u8fdf)</option><option value="6"'+sl('conntype',6,7)+'>LAN(10 Mbps \u6216\u66f4\u9ad8)</option></select></span></div>';
  h+='<div class="cr"><span class="l">\u5141\u8bb8\u4ee5\u4e0b\u9879</span><span class="v"><label><input type="checkbox" id="wf_wall"'+ck('wallpaper',true)+'>\u684c\u9762\u80cc\u666f(B)</label> <label><input type="checkbox" id="wf_font"'+ck('fontsmoothing',false)+'>\u5b57\u4f53\u5e73\u6ed1(F)</label> <label><input type="checkbox" id="wf_comp"'+ck('composition',false)+'>\u684c\u9762\u5e03\u5c40(C)</label> <label><input type="checkbox" id="wf_drag"'+ck('fullwindowdrag',false)+'>\u62d6\u62c9\u65f6\u663e\u793a\u7a97\u53e3\u5185\u5bb9(S)</label></span></div>';
  h+='<div class="cr"><span class="l"></span><span class="v"><label><input type="checkbox" id="wf_anim"'+ck('menuanims',false)+'>\u83dc\u5355\u548c\u7a97\u53e3\u52a8\u753b(M)</label> <label><input type="checkbox" id="wf_theme"'+ck('themes',true)+'>\u89c6\u89c9\u6837\u5f0f(V)</label> <label><input type="checkbox" id="wf_cache"'+ck('bitmapcache',true)+'>\u6301\u4e45\u6027\u4f4d\u56fe\u7f13\u5b58(P)</label></span></div>';
  h+='<div class="cr"><span class="l"></span><span class="v"><label><input type="checkbox" id="wf_reconn"'+ck('autoreconnect',true)+'>\u5982\u679c\u8fde\u63a5\u4e2d\u65ad\u5219\u91cd\u65b0\u8fde\u63a5(R)</label></span></div>';
  h+='</div>';
  h+='<div id="wtab_adv" class="wtab"'+(WTAB==='adv'?'':' style="display:none"')+'>';
  h+='<div class="st">\u670d\u52a1\u5668\u8eab\u4efd\u9a8c\u8bc1</div>';
  h+='<div class="cr"><span class="l">\u5982\u679c\u670d\u52a1\u5668\u8eab\u4efd\u9a8c\u8bc1\u5931\u8d25(F)</span><span class="v"><select id="wf_auth"><option value="2"'+sl('authlevel',2,2)+'>\u8b66\u544a\u6211</option><option value="1"'+sl('authlevel',1,2)+'>\u4e0d\u8fde\u63a5</option><option value="0"'+sl('authlevel',0,2)+'>\u8fde\u63a5\u800c\u4e0d\u53d1\u51fa\u8b66\u544a</option></select></span></div>';
  h+='<div class="st">\u4ece\u4efb\u4f55\u4f4d\u7f6e\u8fde\u63a5 \u00b7 RD \u7f51\u5173\u670d\u52a1\u5668\u8bbe\u7f6e</div>';
  h+='<div class="cr"><span class="l">\u8fde\u63a5\u65b9\u6cd5</span><span class="v"><select id="wf_gwm"><option value="auto"'+gs('auto')+'>\u81ea\u52a8\u68c0\u6d4b RD \u7f51\u5173\u670d\u52a1\u5668\u8bbe\u7f6e(A)</option><option value="manual"'+gs('manual')+'>\u4f7f\u7528\u8fd9\u4e9b RD \u7f51\u5173\u670d\u52a1\u5668\u8bbe\u7f6e(S)</option><option value="none"'+gs('none')+'>\u4e0d\u4f7f\u7528 RD \u7f51\u5173\u670d\u52a1\u5668(O)</option></select></span></div>';
  h+='<div class="cr"><span class="l">\u670d\u52a1\u5668\u540d(V)</span><span class="v"><input id="wf_gw" value="'+iv('gateway')+'"></span></div>';
  h+='<div class="cr"><span class="l"></span><span class="v"><label><input type="checkbox" id="wf_gwbypass"'+ck('gwbypass',true)+'>\u5bf9\u672c\u5730\u5730\u5740\u7ed5\u8fc7 RD \u7f51\u5173\u670d\u52a1\u5668(B)</label> <label><input type="checkbox" id="wf_gwcred"'+ck('gwcreds',true)+'>\u5bf9 RD \u7f51\u5173\u4f7f\u7528\u6211\u7684 RD \u51ed\u636e(N)</label></span></div>';
  h+='</div>';
  h+='</div>'; // .body
  // 官方页脚：连接 / 帮助（右），另存为 / 打开 / 保存（左）——与官方对话框按钮布局同构。
  h+='<div class="footer">';
  h+='<div class="spread"><button onclick="wrSave()">\u4fdd\u5b58(S)</button>'
    +'<button onclick="wrSaveAs()">\u53e6\u5b58\u4e3a(V)\u2026</button>'
    +'<button onclick="post({type:\\'revealDir\\',which:\\'rdp\\'})">\u6253\u5f00(E)\u2026</button></div>';
  h+='<button class="primary" onclick="wrConnect()">\u8fde\u63a5(N)</button>';
  h+='<button onclick="WEDIT=null;render()">\u53d6\u6d88</button>';
  h+='<button onclick="post({type:\\'help\\'})">\u5e2e\u52a9(H)</button>';
  h+='</div>';
  h+='</div>'; // .mstsc
  return h;
}
// 「连接(N)」：先落存档，再以该档案在面板内直开桌面（官方对话框「连接」语义）。
function wrConnect(){
  var g=document.getElementById('wf_name');
  var name=(WEDIT||(g?g.value:'')||'').trim();
  wrSave();
  if(name) post({type:'openDesktop', profile:name});
}
// 「另存为(V)」：解锁连接名输入，以新名另存一份。
function wrSaveAs(){
  var g=document.getElementById('wf_name');
  if(g){ g.disabled=false; g.value=''; g.focus(); }
  WEDIT='';
}
function wrTab(t){ WTAB=t; ['general','display','local','exp','adv'].forEach(function(k){ var el=document.getElementById('wtab_'+k); if(el) el.style.display=(k===t)?'':'none'; });
  document.querySelectorAll('[data-wtab]').forEach(function(b){ b.className=(b.getAttribute('data-wtab')===t)?'sel':''; }); }
function wrRes(el){ var i=parseInt(el.value,10); document.getElementById('wf_reslabel').textContent = i>=WRD_RES.length?'\u5168\u5c4f':(WRD_RES[i][0]+' \u00d7 '+WRD_RES[i][1]+' \u50cf\u7d20'); }
function wrSave(){
  const g=id=>document.getElementById(id);
  const ri=parseInt(g('wf_res').value,10);
  const p={ name:(WEDIT||g('wf_name').value||'').trim(), host:g('wf_host').value.trim(), port:g('wf_port').value.trim(),
    username:g('wf_user').value.trim(), savecred:g('wf_savecred').checked,
    fullscreen:ri>=WRD_RES.length, width:ri<WRD_RES.length?WRD_RES[ri][0]:undefined, height:ri<WRD_RES.length?WRD_RES[ri][1]:undefined,
    multimon:g('wf_multi').checked, bpp:parseInt(g('wf_bpp').value,10), connbar:g('wf_connbar').checked,
    audiomode:parseInt(g('wf_audio').value,10), audiocapture:parseInt(g('wf_audiocap').value,10), keyboardhook:parseInt(g('wf_kbd').value,10),
    printers:g('wf_prn').checked, clipboard:g('wf_clip').checked, smartcards:g('wf_smart').checked,
    ports:g('wf_ports').checked, drives:g('wf_drv').checked, pnp:g('wf_pnp').checked,
    conntype:parseInt(g('wf_conn').value,10), wallpaper:g('wf_wall').checked, fontsmoothing:g('wf_font').checked,
    composition:g('wf_comp').checked, fullwindowdrag:g('wf_drag').checked, menuanims:g('wf_anim').checked,
    themes:g('wf_theme').checked, bitmapcache:g('wf_cache').checked, autoreconnect:g('wf_reconn').checked,
    authlevel:parseInt(g('wf_auth').value,10), gwmethod:g('wf_gwm').value, gateway:g('wf_gw').value.trim(),
    gwbypass:g('wf_gwbypass').checked, gwcreds:g('wf_gwcred').checked };
  if(!p.name){ return; }
  post({type:'rdpSave', profile:p});
  WEDIT=null;
}
function renderConfig(){
  if(WEDIT!==null) return wrForm();
  let h='<div class="card"><div class="cr"><b>\u8fde\u63a5\u6863\u6848\uff08\u5b98\u65b9 .rdp \u00b7 \u4e94\u9875\u5168\u91cf\u76f4\u901a\u9762\u677f\u5185\u684c\u9762\uff09</b>'
    +'<button onclick="WEDIT=\\'\\';WTAB=\\'general\\';render()">\uff0b\u65b0\u5efa</button>'
    +'<button class="ghost" onclick="post({type:\\'revealDir\\',which:\\'rdp\\'})">\u6253\u5f00\u76ee\u5f55</button></div>';
  const rows=(STATE.rdp||[]);
  if(!rows.length) h+='<div class="muted">\uff08\u65e0\u8fde\u63a5\u6863\u6848\uff0c\u70b9\u300c\uff0b\u65b0\u5efa\u300d\u5f00\u59cb\uff09</div>';
  else{
    h+='<table><tr><th>\u8fde\u63a5\u540d</th><th>\u8ba1\u7b97\u673a</th><th>\u7528\u6237\u540d</th><th></th></tr>';
    rows.forEach(function(r){
      h+='<tr><td>'+esc(r.name)+'</td><td>'+esc(r.host||'')+(r.port?':'+esc(r.port):'')+'</td><td>'+esc(r.username||'')+'</td><td class="row">'
        +'<button onclick="post({type:\\'openDesktop\\',profile:\\''+esc(r.name)+'\\'})">\u9762\u677f\u5185\u5f00\u684c\u9762</button>'
        +'<button class="ghost" onclick="post({type:\\'rdpLaunch\\',name:\\''+esc(r.name)+'\\'})">mstsc \u8fde\u63a5</button>'
        +'<button class="ghost" onclick="WEDIT=\\''+esc(r.name)+'\\';WTAB=\\'general\\';render()">\u7f16\u8f91</button>'
        +'<button class="ghost" onclick="post({type:\\'rdpDelete\\',name:\\''+esc(r.name)+'\\'})">\u5220\u9664</button></td></tr>';
    });
    h+='</table>';
  }
  h+='</div>';
  return h;
}
// ── 模块② 账号池：多 Windows 账号生命周期（一账号一路独立桌面）──
function renderPool(){
  let h='<div class="card"><div class="cr"><b>\u8d26\u53f7\u6c60\uff08\u4e00\u8d26\u53f7\u4e00\u8def\u72ec\u7acb\u684c\u9762 \u00b7 \u5355\u5b9e\u4f8b\u8f6f\u4ef6\u4e92\u4e0d\u52ab\u6301\uff09</b>'
    +'<button onclick="post({type:\\'acctCreate\\'})">\uff0b\u65b0\u5efa\u8d26\u53f7</button></div>';
  const rows=(STATE.accounts||[]);
  if(!rows.length) h+='<div class="muted">\uff08\u9698\u9053\u672a\u63a2\u5230\u8d26\u53f7\uff1b\u786e\u8ba4 desktop/tunnel/server.js \u5df2\u542f\u52a8\uff09</div>';
  else{
    h+='<table><tr><th>\u8d26\u53f7</th><th>\u76ee\u6807</th><th></th></tr>';
    rows.forEach(function(a){
      h+='<tr><td>'+esc(a.name)+'</td><td>'+esc(a.hostname||'')+':'+esc(a.port||'')+'</td><td class="row">'
        +'<button onclick="post({type:\\'openDesktop\\',account:\\''+esc(a.name)+'\\'})">\u5f00\u684c\u9762</button>'
        +'<button class="ghost" onclick="post({type:\\'acctDestroy\\',name:\\''+esc(a.name)+'\\'})">\u9500\u6bc1</button></td></tr>';
    });
    h+='</table>';
  }
  h+='</div>';
  return h;
}
function render(){
  document.getElementById('mTabConfig').className = WMOD==='config'?'':'ghost';
  document.getElementById('mTabPool').className = WMOD==='pool'?'':'ghost';
  document.getElementById('main').innerHTML = WMOD==='pool'?renderPool():renderConfig();
}
window.addEventListener('message', function(ev){
  const m = ev.data||{};
  if(m.type==='state'){ STATE = m.data||{}; render(); }
});
render();
</script></body></html>`;
}

module.exports = { winHomeHtml, WRD_RES };
