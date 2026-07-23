// dao-one-windows · 注入负载 — 把 🪟 Windows 板块作为原 dao-one/9920 全能板(getDaoCloudMiddlePanelHtml)
// 的同级 tab 折入, 不另起任何新前端/新面板/新宿主。负载分两半:
//   FRONTEND_JS  — 插进全能板模板 <script> 内(位于 usb(); 收尾行之前)。因模板是 JS 模板字面量,
//                  本段严禁出现反引号与 "$" + "{" 序列(全部用字符串拼接)。
//   HOST_HELPERS — 插进宿主 handleMiddlePanelMessage 之前(RDP 档案落盘/.rdp 生成/mstsc 启动)。
//   HOST_CASES   — 插进 handleMiddlePanelMessage 的 switch(msg.command) 开头。
//   NOAUTH_ADD   — 追加进免登录命令白名单(RDP 管理与 Devin 账号登录无关)。
"use strict";

// 官方「远程桌面连接」五页(常规/显示/本地资源/体验/高级) 1:1 收编, 控件与措辞同官方,
// 每个控件对应标准 .rdp 键; 保存 → .json+.rdp, 连接 → mstsc.exe(仅 Windows)。
const FRONTEND_JS = [
"/* ── dao-one-windows · 🪟 Windows 归一板块(全能板同级 tab) ──",
"   本源(正本清源之再正本清源): Windows 收敛为两模块 + N 路独立桌面板块 —",
"   ① 统一配置管理台(官方 mstsc 五页全功能收编 · 连接档案);",
"   ② 账号池(仿切号板 · 多 Windows 账号生命周期, 对齐 core/accounts.py 语义);",
"   ③ 远程桌面 = 官方 Apache Guacamole 引擎把整块 Windows 桌面渲染进本面板同一页(非 mstsc · 非自造 rdpjs · 非浏览器顶层)。*/",
"var WRD={list:null,edit:null};",
"var WACC={list:null,creating:false};",
"var WMOD='config';",
"var WRD_RES=[[640,480],[800,600],[1024,768],[1280,720],[1366,768],[1600,900],[1920,1080],[2560,1440]];",
"function wrCur(){if(WRD.edit===''||WRD.edit===null)return {};var p={};(WRD.list||[]).forEach(function(x){if(x.name===WRD.edit)p=x;});return p;}",
"function wrForm(){var p=wrCur();",
"  function iv(k,d){var v=p[k]!==undefined?p[k]:(d===undefined?'':d);return esc(String(v));}",
"  function ck(k,d){return (p[k]!==undefined?p[k]:d)?' checked':'';}",
"  function sl(k,v,d){return String(p[k]===undefined?d:p[k])===String(v)?' selected':'';}",
"  var gcur=p.gwmethod!==undefined?p.gwmethod:(p.gateway?'manual':'auto');",
"  function gs(v){return gcur===v?' selected':'';}",
"  var ri=WRD_RES.length;",
"  if(p.fullscreen===false){ri=-1;for(var i=0;i<WRD_RES.length;i++){if(String(WRD_RES[i][0])===String(p.width)&&String(WRD_RES[i][1])===String(p.height))ri=i;}if(ri<0)ri=6;}",
"  var resLabel=ri>=WRD_RES.length?'全屏':(WRD_RES[ri][0]+' × '+WRD_RES[ri][1]+' 像素');",
"  var h='<div class=\"card\"><div class=\"cr\"><span class=\"l\"><b>'+(WRD.edit?'编辑':'新建')+' · 远程桌面连接</b></span><span class=\"v\" style=\"color:var(--muted)\">官方对话框原样收编 → 标准 .rdp · 连接即 mstsc</span></div>';",
"  h+='<div class=\"cr\"><span class=\"v\" style=\"display:flex;gap:4px;flex-wrap:wrap\">'+[['general','常规'],['display','显示'],['local','本地资源'],['exp','体验'],['adv','高级']].map(function(t,i){return '<button class=\"btn'+(i?' ghost':'')+'\" data-wtab=\"'+t[0]+'\" onclick=\"wrTab(&#39;'+t[0]+'&#39;)\">'+t[1]+'</button>';}).join('')+'</span></div>';",
"  h+='<div id=\"wtab_general\" class=\"wtab\">';",
"  h+='<div class=\"st\">登录设置</div>';",
"  h+='<div class=\"cr\"><span class=\"l\">计算机(C)</span><span class=\"v\"><input id=\"wf_host\" placeholder=\"示例: computer.fabrikam.com\" value=\"'+iv('host')+'\"> : <input id=\"wf_port\" size=\"5\" placeholder=\"3389\" value=\"'+iv('port')+'\"></span></div>';",
"  h+='<div class=\"cr\"><span class=\"l\">用户名</span><span class=\"v\"><input id=\"wf_user\" value=\"'+iv('username')+'\"></span></div>';",
"  h+='<div class=\"cr\"><span class=\"l\"></span><span class=\"v\" style=\"color:var(--muted)\">当你连接时将向你询问凭据。</span></div>';",
"  h+='<div class=\"cr\"><span class=\"l\"></span><span class=\"v\"><label><input type=\"checkbox\" id=\"wf_savecred\"'+ck('savecred',false)+'>允许我保存凭据(R)</label></span></div>';",
"  h+='<div class=\"st\">连接设置</div>';",
"  h+='<div class=\"cr\"><span class=\"l\">连接名</span><span class=\"v\"><input id=\"wf_name\" placeholder=\"保存的连接名(.rdp 文件名)\" value=\"'+iv('name')+'\"'+(WRD.edit?' disabled':'')+'></span></div>';",
"  h+='</div>';",
"  h+='<div id=\"wtab_display\" class=\"wtab\" style=\"display:none\">';",
"  h+='<div class=\"st\">显示配置</div>';",
"  h+='<div class=\"cr\"><span class=\"l\">选择远程桌面的大小</span><span class=\"v\">小 <input type=\"range\" id=\"wf_res\" min=\"0\" max=\"'+WRD_RES.length+'\" step=\"1\" value=\"'+ri+'\" style=\"vertical-align:middle\" oninput=\"wrRes(this)\"> 大 · <span id=\"wf_reslabel\">'+resLabel+'</span></span></div>';",
"  h+='<div class=\"cr\"><span class=\"l\"></span><span class=\"v\"><label><input type=\"checkbox\" id=\"wf_multi\"'+ck('multimon',false)+'>将我的所有监视器用于远程会话(U)</label></span></div>';",
"  h+='<div class=\"st\">颜色</div>';",
"  h+='<div class=\"cr\"><span class=\"l\">选择远程会话的颜色深度(C)</span><span class=\"v\"><select id=\"wf_bpp\"><option value=\"15\"'+sl('bpp',15,32)+'>增强色(15 位)</option><option value=\"16\"'+sl('bpp',16,32)+'>增强色(16 位)</option><option value=\"24\"'+sl('bpp',24,32)+'>真彩色(24 位)</option><option value=\"32\"'+sl('bpp',32,32)+'>最高质量(32 位)</option></select></span></div>';",
"  h+='<div class=\"cr\"><span class=\"l\"></span><span class=\"v\"><label><input type=\"checkbox\" id=\"wf_connbar\"'+ck('connbar',true)+'>全屏显示时显示连接栏(D)</label></span></div>';",
"  h+='</div>';",
"  h+='<div id=\"wtab_local\" class=\"wtab\" style=\"display:none\">';",
"  h+='<div class=\"st\">远程音频</div>';",
"  h+='<div class=\"cr\"><span class=\"l\">远程音频播放</span><span class=\"v\"><select id=\"wf_audio\"><option value=\"0\"'+sl('audiomode',0,0)+'>在此计算机上播放</option><option value=\"2\"'+sl('audiomode',2,0)+'>不播放</option><option value=\"1\"'+sl('audiomode',1,0)+'>在远程计算机上播放</option></select></span></div>';",
"  h+='<div class=\"cr\"><span class=\"l\">远程音频录制</span><span class=\"v\"><select id=\"wf_audiocap\"><option value=\"0\"'+sl('audiocapture',0,0)+'>不要录制</option><option value=\"1\"'+sl('audiocapture',1,0)+'>从此计算机录制</option></select></span></div>';",
"  h+='<div class=\"st\">键盘</div>';",
"  h+='<div class=\"cr\"><span class=\"l\">应用 Windows 组合键(K)</span><span class=\"v\"><select id=\"wf_kbd\"><option value=\"2\"'+sl('keyboardhook',2,2)+'>仅在使用全屏时</option><option value=\"0\"'+sl('keyboardhook',0,2)+'>在此计算机上</option><option value=\"1\"'+sl('keyboardhook',1,2)+'>在远程计算机上</option></select></span></div>';",
"  h+='<div class=\"st\">本地设备和资源</div>';",
"  h+='<div class=\"cr\"><span class=\"l\"></span><span class=\"v\"><label><input type=\"checkbox\" id=\"wf_prn\"'+ck('printers',true)+'>打印机(T)</label> <label><input type=\"checkbox\" id=\"wf_clip\"'+ck('clipboard',true)+'>剪贴板(L)</label></span></div>';",
"  h+='<div class=\"cr\"><span class=\"l\">详细信息(M)</span><span class=\"v\"><label><input type=\"checkbox\" id=\"wf_smart\"'+ck('smartcards',true)+'>智能卡</label> <label><input type=\"checkbox\" id=\"wf_ports\"'+ck('ports',false)+'>端口</label> <label><input type=\"checkbox\" id=\"wf_drv\"'+ck('drives',false)+'>驱动器</label> <label><input type=\"checkbox\" id=\"wf_pnp\"'+ck('pnp',false)+'>其他支持的即插即用设备</label></span></div>';",
"  h+='</div>';",
"  h+='<div id=\"wtab_exp\" class=\"wtab\" style=\"display:none\">';",
"  h+='<div class=\"st\">性能</div>';",
"  h+='<div class=\"cr\"><span class=\"l\">选择连接速度来优化性能(P)</span><span class=\"v\"><select id=\"wf_conn\"><option value=\"7\"'+sl('conntype',7,7)+'>自动检测连接质量(A)</option><option value=\"1\"'+sl('conntype',1,7)+'>调制解调器(56 kbps)</option><option value=\"2\"'+sl('conntype',2,7)+'>低速宽带(256 kbps - 2 Mbps)</option><option value=\"3\"'+sl('conntype',3,7)+'>卫星(2 Mbps - 16 Mbps, 高延迟)</option><option value=\"4\"'+sl('conntype',4,7)+'>高速宽带(2 Mbps - 10 Mbps)</option><option value=\"5\"'+sl('conntype',5,7)+'>WAN(10 Mbps 或更高, 高延迟)</option><option value=\"6\"'+sl('conntype',6,7)+'>LAN(10 Mbps 或更高)</option></select></span></div>';",
"  h+='<div class=\"cr\"><span class=\"l\">允许以下项</span><span class=\"v\"><label><input type=\"checkbox\" id=\"wf_wall\"'+ck('wallpaper',true)+'>桌面背景(B)</label> <label><input type=\"checkbox\" id=\"wf_font\"'+ck('fontsmoothing',false)+'>字体平滑(F)</label> <label><input type=\"checkbox\" id=\"wf_comp\"'+ck('composition',false)+'>桌面布局(C)</label> <label><input type=\"checkbox\" id=\"wf_drag\"'+ck('fullwindowdrag',false)+'>拖拉时显示窗口内容(S)</label></span></div>';",
"  h+='<div class=\"cr\"><span class=\"l\"></span><span class=\"v\"><label><input type=\"checkbox\" id=\"wf_anim\"'+ck('menuanims',false)+'>菜单和窗口动画(M)</label> <label><input type=\"checkbox\" id=\"wf_theme\"'+ck('themes',true)+'>视觉样式(V)</label> <label><input type=\"checkbox\" id=\"wf_cache\"'+ck('bitmapcache',true)+'>持久性位图缓存(P)</label></span></div>';",
"  h+='<div class=\"cr\"><span class=\"l\"></span><span class=\"v\"><label><input type=\"checkbox\" id=\"wf_reconn\"'+ck('autoreconnect',true)+'>如果连接中断则重新连接(R)</label></span></div>';",
"  h+='</div>';",
"  h+='<div id=\"wtab_adv\" class=\"wtab\" style=\"display:none\">';",
"  h+='<div class=\"st\">服务器身份验证</div>';",
"  h+='<div class=\"cr\"><span class=\"l\">如果服务器身份验证失败(F)</span><span class=\"v\"><select id=\"wf_auth\"><option value=\"2\"'+sl('authlevel',2,2)+'>警告我</option><option value=\"1\"'+sl('authlevel',1,2)+'>不连接</option><option value=\"0\"'+sl('authlevel',0,2)+'>连接而不发出警告</option></select></span></div>';",
"  h+='<div class=\"st\">从任何位置连接 · RD 网关服务器设置</div>';",
"  h+='<div class=\"cr\"><span class=\"l\">连接方法</span><span class=\"v\"><select id=\"wf_gwm\"><option value=\"auto\"'+gs('auto')+'>自动检测 RD 网关服务器设置(A)</option><option value=\"manual\"'+gs('manual')+'>使用这些 RD 网关服务器设置(S)</option><option value=\"none\"'+gs('none')+'>不使用 RD 网关服务器(O)</option></select></span></div>';",
"  h+='<div class=\"cr\"><span class=\"l\">服务器名(V)</span><span class=\"v\"><input id=\"wf_gw\" value=\"'+iv('gateway')+'\"></span></div>';",
"  h+='<div class=\"cr\"><span class=\"l\"></span><span class=\"v\"><label><input type=\"checkbox\" id=\"wf_gwbypass\"'+ck('gwbypass',true)+'>对本地地址绕过 RD 网关服务器(B)</label> <label><input type=\"checkbox\" id=\"wf_gwcred\"'+ck('gwcreds',true)+'>对 RD 网关使用我的 RD 凭据(N)</label></span></div>';",
"  h+='</div>';",
"  h+='<div class=\"cr\"><span class=\"l\"></span><span class=\"v\"><button class=\"btn primary\" onclick=\"wrSave()\">保存(.json+.rdp)</button> <button class=\"btn ghost\" onclick=\"wrCancel()\">取消</button></span></div></div>';",
"  return h;}",
"/* ── 板块外壳: 分而治之 —— 本板块只做「统一管理面」(① 官方 mstsc 五页配置台 / ② 多账号池),",
"   远程桌面本体不再内嵌于此: 点「开桌面」即在顶层页面栏新开一张独立页(类 Devin 多实例, 一账号一页,",
"   多页并行·互不干扰·道并行而不相悖), 整页只呈现该账号的整块 Windows 桌面(官方 Guacamole 引擎)。*/",
"function rWindows(){var v=document.getElementById('v-windows');if(!v)return;",
"  var main=document.getElementById('wmain');",
"  if(!main){main=document.createElement('div');main.id='wmain';v.appendChild(main);}",
"  var sw='<div class=\"st\">🪟 Windows · 统一管理面(官方远程桌面全功能收编 · 开桌面=顶层独立页 · 分而治之)</div>';",
"  sw+='<div class=\"card\"><div class=\"cr\"><span class=\"v\" style=\"display:flex;gap:6px;flex-wrap:wrap\">'+",
"    '<button class=\"btn'+(WMOD==='config'?'':' ghost')+'\" onclick=\"wmSwitch(&#39;config&#39;)\">① 统一配置管理台</button>'+",
"    '<button class=\"btn'+(WMOD==='pool'?'':' ghost')+'\" onclick=\"wmSwitch(&#39;pool&#39;)\">② 账号池 · 多账号管理</button>'+",
"    '</span></div></div>';",
"  if(WMOD==='pool'){rWinPool(main,sw);return;}",
"  rWinConfig(main,sw);}",
"function wmSwitch(m){WMOD=(m==='pool'?'pool':'config');rWindows();}",
"/* 开桌面 = 顶层页面栏新开独立页: 先确保官方 Guacamole 引擎(guacd+隧道)就位并把目标登记进隧道账号注册表,",
"   再把 /desktop?account=<账号> 作为一张顶层 iframe 页交给外壳(/shell)开启(如 Devin 多实例, 一账号一页)。 */",
"var WDESKOPTS={};",
"function wdeskOpen(account,label,target,opts){if(!account){toast('缺账号/连接名',false);return;}",
"  WDESKOPTS[account]=opts||null;",
"  toast('打开远程桌面页 · '+(label||account),true);cmd('winDeskEnsure',{account:account,label:(label||account),target:target||null});}",
"/* .rdp 档案键 → 官方 token 会话选项(剪贴板/驱动器重定向等) —— 只搬运不生产, 逐键直通隙道 /token。 */",
"function wdeskOptsQ(o){if(!o)return '';var q='';",
"  if(o.clipboard===false)q+='&clipboard=off';",
"  if(o.drives)q+='&drive='+encodeURIComponent('C:\\\\dao-share');",
"  if(o.readonly)q+='&readonly=1';",
"  return q;}",
"function daoWinDeskReady(d){if(d&&d.error){toast('官方引擎未就绪: '+d.error,false);return;}",
"  if(!d||!d.url||!d.account)return;",
"  var lbl=d.label||d.account;",
"  var u=d.url+'?account='+encodeURIComponent(d.account)+'&label='+encodeURIComponent(lbl)+'&lock=1&autoconnect=1'+wdeskOptsQ(WDESKOPTS[d.account]);",
"  var msg={type:'open',id:'wdesk:'+d.account,url:u,label:'🖥 '+lbl,email:d.account};",
"  try{if(window.parent&&window.parent!==window){window.parent.postMessage(msg,'*');}",
"    else if(window.top&&window.top!==window){window.top.postMessage(msg,'*');}",
"    else{cmd('winDeskOpenExternal',{url:u});}}catch(e){cmd('winDeskOpenExternal',{url:u});}}",
"/* ── 模块① 统一配置管理台: 官方 mstsc 五页连接档案 ── */",
"function rWinConfig(v,h){",
"  if(WRD.list===null){v.innerHTML=h+'<div class=\"empty\"><div class=\"ic\">🪟</div><p style=\"color:var(--muted)\">加载连接档案…</p></div>';cmd('winRdpList');return;}",
"  h+='<div class=\"card\"><div class=\"cr\"><span class=\"l\">连接档案 '+WRD.list.length+' 个 · 官方五页全功能收编</span><span class=\"v\"><button class=\"btn primary\" onclick=\"wrNew()\">＋新建</button> <button class=\"btn ghost\" onclick=\"cmd(&#39;winRdpOpenDir&#39;)\">打开目录</button> <button class=\"btn ghost\" onclick=\"wrReload()\">⟳</button></span></div></div>';",
"  for(var i=0;i<WRD.list.length;i++){var p=WRD.list[i];",
"    h+='<div class=\"card\"><div class=\"cr\"><span class=\"l\">🖥 '+esc(p.name||'')+'</span><span class=\"v\">'+",
"      '<button class=\"btn primary\" onclick=\"wrOpenDesk('+i+')\">开桌面(独立页)</button> '+",
"      '<button class=\"btn ghost\" onclick=\"wrGo('+i+')\">官方 mstsc</button> '+",
"      '<button class=\"btn ghost\" onclick=\"wrEdit('+i+')\">编辑</button> '+",
"      '<button class=\"btn danger\" onclick=\"wrDel('+i+')\">删除</button></span></div>'+",
"      '<div class=\"cr\"><span class=\"l\" style=\"color:var(--muted)\">'+esc(p.host||'')+(p.port?':'+esc(String(p.port)):'')+(p.username?' · '+esc(p.username):'')+'</span></div></div>';}",
"  if(WRD.edit!==null)h+=wrForm();",
"  v.innerHTML=h;}",
"function wrReload(){WRD.list=null;rWindows();}",
"function wrNew(){WRD.edit='';rWindows();}",
"function wrEdit(i){var p=WRD.list[i];if(p)WRD.edit=p.name;rWindows();}",
"function wrDel(i){var p=WRD.list[i];if(!p)return;WRD.edit=null;WRD.list=null;rWindows();cmd('winRdpDel',{name:p.name});}",
"function wrGo(i){var p=WRD.list[i];if(p)cmd('winRdpConnect',{name:p.name});}",
"function wrOpenDesk(i){var p=WRD.list[i];if(!p)return;wdeskOpen(p.name,p.name,{hostname:(p.host||'127.0.0.1'),port:(p.port||'3389'),username:(p.username||'')},{clipboard:p.clipboard,drives:p.drives});}",
"function wrCancel(){WRD.edit=null;rWindows();}",
"/* ── 模块② 账号池(仿切号板 · 多 Windows 账号生命周期) ── */",
"function rWinPool(v,h){",
"  if(WACC.list===null){v.innerHTML=h+'<div class=\"empty\"><div class=\"ic\">👥</div><p style=\"color:var(--muted)\">加载 Windows 账号…</p></div>';cmd('winAcctList');return;}",
"  h+='<div class=\"card\"><div class=\"cr\"><span class=\"l\">Windows 账号 '+WACC.list.length+' 个 · 每账号一路独立桌面(RDPWrap 多会话)</span><span class=\"v\"><button class=\"btn primary\" onclick=\"waNew()\">＋建号</button> <button class=\"btn ghost\" onclick=\"waReload()\">⟳</button></span></div></div>';",
"  if(WACC.creating)h+=waForm();",
"  for(var i=0;i<WACC.list.length;i++){var a=WACC.list[i];",
"    var sess=a.session?('● 会话 '+esc(String(a.session.id||''))+' · '+esc(String(a.session.state||''))):'○ 无会话';",
"    var tgt=(a.target&&a.target.hostname?esc(String(a.target.hostname))+':'+esc(String(a.target.port||'3389')):'127.0.0.1:3389');",
"    h+='<div class=\"card\"><div class=\"cr\"><span class=\"l\">👤 '+esc(a.name||'')+(a.admin?' · 管理员':'')+(a.managed?' · 归一建号':'')+'</span><span class=\"v\">'+",
"      '<button class=\"btn primary\" onclick=\"waOpenDesk('+i+')\">开桌面(独立页)</button> '+",
"      (a.session?('<button class=\"btn ghost\" onclick=\"waLogoff('+i+')\">注销会话</button> '):'')+",
"      '<button class=\"btn danger\" onclick=\"waDel('+i+')\">删号</button></span></div>'+",
"      '<div class=\"cr\"><span class=\"l\" style=\"color:var(--muted)\">'+sess+' · RDP '+tgt+'</span></div></div>';}",
"  v.innerHTML=h;}",
"function waForm(){var h='<div class=\"card\"><div class=\"cr\"><span class=\"l\"><b>建号 · 新建 Windows 本地账号</b></span><span class=\"v\" style=\"color:var(--muted)\">New-LocalUser + 加入 Remote Desktop Users(需管理员)</span></div>';",
"  h+='<div class=\"cr\"><span class=\"l\">账号名</span><span class=\"v\"><input id=\"wa_name\" placeholder=\"字母数字与 . _ - , ≤20\"></span></div>';",
"  h+='<div class=\"cr\"><span class=\"l\">密码</span><span class=\"v\"><input id=\"wa_pw\" type=\"password\" placeholder=\"留空用默认强口令\"></span></div>';",
"  h+='<div class=\"cr\"><span class=\"l\"></span><span class=\"v\"><label><input type=\"checkbox\" id=\"wa_admin\">同时加入 Administrators</label></span></div>';",
"  h+='<div class=\"cr\"><span class=\"l\"></span><span class=\"v\"><button class=\"btn primary\" onclick=\"waCreate()\">创建</button> <button class=\"btn ghost\" onclick=\"waCancel()\">取消</button></span></div></div>';",
"  return h;}",
"function waReload(){WACC.list=null;rWindows();}",
"function waNew(){WACC.creating=true;rWindows();}",
"function waCancel(){WACC.creating=false;rWindows();}",
"function waCreate(){var g=function(id){return document.getElementById(id);};var name=g('wa_name').value.trim();if(!name){toast('账号名不能为空',false);return;}var pw=g('wa_pw').value;var admin=g('wa_admin').checked;WACC.creating=false;WACC.list=null;rWindows();cmd('winAcctCreate',{name:name,password:pw,admin:admin});}",
"function waDel(i){var a=WACC.list[i];if(!a)return;if(typeof confirm==='function'&&!confirm('确认删除 Windows 账号 “'+a.name+'” 及其用户配置? 不可逆。'))return;WACC.list=null;rWindows();cmd('winAcctDestroy',{name:a.name});}",
"function waLogoff(i){var a=WACC.list[i];if(!a||!a.session)return;if(typeof confirm==='function'&&!confirm('确认注销 “'+a.name+'” 的会话 '+a.session.id+'?'))return;WACC.list=null;rWindows();cmd('winAcctLogoff',{id:a.session.id});}",
"function waOpenDesk(i){var a=WACC.list[i];if(!a)return;var t=a.target||{};wdeskOpen(a.name,a.name,{hostname:(t.hostname||'127.0.0.1'),port:(t.port||'3389'),username:a.name});}",

"function wrTab(t){document.querySelectorAll('.wtab').forEach(function(d){d.style.display='none';});var pane=document.getElementById('wtab_'+t);if(pane)pane.style.display='';document.querySelectorAll('[data-wtab]').forEach(function(b){b.className='btn ghost';});var el=document.querySelector('[data-wtab=\"'+t+'\"]');if(el)el.className='btn';}",
"function wrRes(el){var i=parseInt(el.value,10);var lb=document.getElementById('wf_reslabel');if(lb)lb.textContent=i>=WRD_RES.length?'全屏':(WRD_RES[i][0]+' × '+WRD_RES[i][1]+' 像素');}",
"function wrSave(){function g(id){return document.getElementById(id);}",
"  var name=g('wf_name').value.trim();if(!name){toast('连接名不能为空',false);return;}",
"  var ri=parseInt(g('wf_res').value,10);var full=ri>=WRD_RES.length;var res=full?[1920,1080]:WRD_RES[ri];",
"  var prof={name:name,host:g('wf_host').value.trim(),port:g('wf_port').value.trim(),username:g('wf_user').value.trim(),savecred:g('wf_savecred').checked,",
"    fullscreen:full,width:res[0],height:res[1],multimon:g('wf_multi').checked,bpp:g('wf_bpp').value,connbar:g('wf_connbar').checked,",
"    audiomode:g('wf_audio').value,audiocapture:g('wf_audiocap').value,keyboardhook:g('wf_kbd').value,",
"    printers:g('wf_prn').checked,clipboard:g('wf_clip').checked,smartcards:g('wf_smart').checked,ports:g('wf_ports').checked,drives:g('wf_drv').checked,pnp:g('wf_pnp').checked,",
"    conntype:g('wf_conn').value,wallpaper:g('wf_wall').checked,fontsmoothing:g('wf_font').checked,composition:g('wf_comp').checked,fullwindowdrag:g('wf_drag').checked,menuanims:g('wf_anim').checked,themes:g('wf_theme').checked,bitmapcache:g('wf_cache').checked,autoreconnect:g('wf_reconn').checked,",
"    authlevel:g('wf_auth').value,gwmethod:g('wf_gwm').value,gateway:g('wf_gw').value.trim(),gwbypass:g('wf_gwbypass').checked,gwcreds:g('wf_gwcred').checked};",
"  WRD.edit=null;WRD.list=null;rWindows();cmd('winRdpSave',{profile:prof});}",
"window.addEventListener('message',function(ev){var d=ev.data||{};",
"  if(d.type==='winRdpData'){WRD.list=d.items||[];if(d.reset)WRD.edit=null;if(S.tab==='windows')rWindows();}",
"  else if(d.type==='winAcctData'){WACC.list=d.items||[];if(S.tab==='windows')rWindows();}",
"  else if(d.type==='winDeskReady'){daoWinDeskReady(d);}});",
].join("\n");

// 宿主侧: RDP 档案落盘(~/.dao/rdp) + 标准 .rdp 生成 + 官方 mstsc.exe 启动(仅 Windows)。
// 与官方「远程桌面连接」五页字段 1:1 映射; 不写入任何密码/凭据。
const HOST_HELPERS = `// ── dao-one-windows · 🪟 Windows 板块宿主原语(官方 mstsc 收编 · 不出凭据) ──
function daoWinRdpDir() {
    const d = path.join(os.homedir(), '.dao', 'rdp');
    try { fs.mkdirSync(d, { recursive: true, mode: 0o700 }); } catch (e) { /* 守柔 */ }
    return d;
}
function daoWinRdpSafeName(name) {
    return String(name || '').replace(/[\\\\/:*?"<>|\\r\\n]/g, '').trim().slice(0, 120);
}
function daoWinRdpList() {
    const dir = daoWinRdpDir();
    const out = [];
    let files = [];
    try { files = fs.readdirSync(dir); } catch (e) { return out; }
    for (const f of files) {
        if (!f.endsWith('.json')) continue;
        try { out.push(JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8'))); } catch (e) { /* 守柔 */ }
    }
    out.sort((a, b) => String(a.name || '').localeCompare(String(b.name || '')));
    return out;
}
function daoWinRdpFileContent(p) {
    const b = (v, d) => (v === undefined || v === null ? d : (v ? 1 : 0));
    const num = (v, d) => { const n = parseInt(v, 10); return Number.isFinite(n) ? n : d; };
    const gw = p.gwmethod || (p.gateway ? 'manual' : 'auto');
    const conntype = num(p.conntype, 7);
    const lines = [
        'full address:s:' + (p.host || '') + (p.port && String(p.port) !== '3389' && String(p.port) !== '' ? ':' + p.port : ''),
        'username:s:' + (p.username || ''),
        'prompt for credentials:i:' + (p.savecred ? 0 : b(p.promptcred, 0)),
        'screen mode id:i:' + (p.fullscreen === false ? 1 : 2),
        'desktopwidth:i:' + num(p.width, 1920),
        'desktopheight:i:' + num(p.height, 1080),
        'session bpp:i:' + num(p.bpp, 32),
        'use multimon:i:' + b(p.multimon, 0),
        'displayconnectionbar:i:' + b(p.connbar, 1),
        'smart sizing:i:1',
        'audiomode:i:' + num(p.audiomode, 0),
        'audiocapturemode:i:' + num(p.audiocapture, 0),
        'keyboardhook:i:' + num(p.keyboardhook, 2),
        'redirectclipboard:i:' + b(p.clipboard, 1),
        'redirectprinters:i:' + b(p.printers, 0),
        'redirectsmartcards:i:' + b(p.smartcards, 1),
        'redirectcomports:i:' + b(p.ports, 0),
        'drivestoredirect:s:' + (p.drives ? '*' : ''),
        'devicestoredirect:s:' + (p.pnp ? '*' : ''),
        'connection type:i:' + conntype,
        'networkautodetect:i:' + (conntype === 7 ? 1 : b(p.autodetect, 0)),
        'bandwidthautodetect:i:' + (conntype === 7 ? 1 : 0),
        'disable wallpaper:i:' + (b(p.wallpaper, 1) ? 0 : 1),
        'allow font smoothing:i:' + b(p.fontsmoothing, 0),
        'allow desktop composition:i:' + b(p.composition, 0),
        'disable full window drag:i:' + (b(p.fullwindowdrag, 0) ? 0 : 1),
        'disable menu anims:i:' + (b(p.menuanims, 0) ? 0 : 1),
        'disable themes:i:' + (b(p.themes, 1) ? 0 : 1),
        'bitmapcachepersistenable:i:' + b(p.bitmapcache, 1),
        'compression:i:1',
        'autoreconnection enabled:i:' + b(p.autoreconnect, 1),
        'authentication level:i:' + num(p.authlevel, 2),
        'gatewayhostname:s:' + (gw === 'manual' ? (p.gateway || '') : ''),
        'gatewayusagemethod:i:' + (gw === 'manual' ? (b(p.gwbypass, 1) ? 2 : 1) : gw === 'none' ? 0 : 4),
        'gatewayprofileusagemethod:i:' + (gw === 'auto' ? 0 : 1),
        'gatewaycredentialssource:i:4',
        'promptcredentialonce:i:' + b(p.gwcreds, 1),
        'remoteapplicationmode:i:0',
    ];
    return lines.join('\\r\\n') + '\\r\\n';
}
function daoWinRdpSave(profile) {
    const name = daoWinRdpSafeName(profile && profile.name);
    if (!name) return { error: '连接名不能为空' };
    const p = Object.assign({}, profile, { name });
    const dir = daoWinRdpDir();
    try {
        fs.writeFileSync(path.join(dir, name + '.json'), JSON.stringify(p, null, 2), 'utf8');
        fs.writeFileSync(path.join(dir, name + '.rdp'), daoWinRdpFileContent(p), 'utf8');
        return { ok: true };
    } catch (e) { return { error: String(e && e.message || e) }; }
}
function daoWinRdpDel(name) {
    const n = daoWinRdpSafeName(name);
    if (!n) return { error: '缺连接名' };
    const dir = daoWinRdpDir();
    try { fs.unlinkSync(path.join(dir, n + '.json')); } catch (e) { /* 守柔 */ }
    try { fs.unlinkSync(path.join(dir, n + '.rdp')); } catch (e) { /* 守柔 */ }
    return { ok: true };
}
function daoWinRdpConnect(name) {
    const n = daoWinRdpSafeName(name);
    const file = path.join(daoWinRdpDir(), n + '.rdp');
    if (!fs.existsSync(file)) return { error: '未找到 ' + n + '.rdp(先保存)' };
    if (process.platform !== 'win32') return { error: '仅 Windows 本机可启动官方 mstsc.exe' };
    try {
        const cp = require('child_process');
        const child = cp.spawn('mstsc.exe', [file], { detached: true, stdio: 'ignore', windowsHide: false });
        child.unref();
        return { ok: true };
    } catch (e) { return { error: String(e && e.message || e) }; }
}
// ── route A · 远程桌面独立页(官方 Apache Guacamole 引擎 → 顶层页面栏一账号一页 · 非 mstsc) ──
// 链路: 顶层页 iframe(/desktop?account=X 单页客户端) → guacamole-lite 隧道(WS 4823/HTTP 4824) → guacd(WSL 4822) → RDP 3389。
// 凭据由隧道持有并铸加密 token, 不下发面板。此原语确保 guacd+隧道在位、把目标登记进隧道账号注册表, 并给出 /desktop 地址。
const DAO_TUNNEL_HTTP_PORT = parseInt(process.env.DAO_GUAC_HTTP_PORT || '4824', 10);
// 隧道账号注册表(account → RDP 目标 · 无口令): 专用文件, 隧道经 DAO_ACCOUNTS_JSON 活读。
// 绝不写 ~/.dao/accounts.json(Devin 登录态池); 口令仍留隧道侧 DEFAULT_RDP/环境, 不经面板。
function daoWinGuacAcctPath() { return path.join(os.homedir(), '.dao', 'win-guac-accounts.json'); }
function daoWinGuacAcctSync(account, target) {
    if (!account) return;
    const p = daoWinGuacAcctPath();
    let reg = {};
    try { reg = JSON.parse(fs.readFileSync(p, 'utf8')); } catch (e) { /* 守柔 */ }
    if (!reg || typeof reg !== 'object' || Array.isArray(reg)) reg = {};
    const t = target || {};
    const old = (reg[account] && typeof reg[account] === 'object') ? reg[account] : {};
    reg[account] = Object.assign({}, old, {
        hostname: t.hostname || old.hostname || '127.0.0.1',
        port: String(t.port || old.port || '3389'),
        username: t.username || old.username || account,
    });
    try { fs.mkdirSync(path.dirname(p), { recursive: true, mode: 0o700 }); } catch (e) { /* 守柔 */ }
    try { fs.writeFileSync(p, JSON.stringify(reg, null, 2), 'utf8'); } catch (e) { /* 守柔 */ }
}
function daoTcpUp(port) {
    return new Promise((resolve) => {
        const net = require('net');
        let done = false;
        const s = net.connect(port, '127.0.0.1');
        const fin = (v) => { if (!done) { done = true; try { s.destroy(); } catch (e) { /* 守柔 */ } resolve(v); } };
        s.on('connect', () => fin(true));
        s.on('error', () => fin(false));
        setTimeout(() => fin(false), 800);
    });
}
function daoWinTunnelDir() {
    const cands = [];
    if (process.env.DAO_TUNNEL_DIR) cands.push(process.env.DAO_TUNNEL_DIR);
    cands.push('C:/dao_vm/guactunnel');
    cands.push(path.join(os.homedir(), '.dao', 'guactunnel'));
    for (const d of cands) { try { if (d && fs.existsSync(path.join(d, 'server.js'))) return d; } catch (e) { /* 守柔 */ } }
    return null;
}
async function daoWinDeskEnsure(opts) {
    if (process.platform !== 'win32') return { error: '远程桌面仅 Windows 本机可用' };
    opts = opts || {};
    if (opts.account) daoWinGuacAcctSync(opts.account, opts.target);
    const baseUrl = 'http://127.0.0.1:' + DAO_TUNNEL_HTTP_PORT + '/desktop';
    const ret = { ok: true, url: baseUrl, account: opts.account || null, label: opts.label || opts.account || null };
    if (await daoTcpUp(DAO_TUNNEL_HTTP_PORT)) return ret;
    const cp = require('child_process');
    // guacd 跑在 WSL(systemd 托管) —— best-effort 拉起, 静默容错
    try {
        cp.spawn('wsl.exe', ['-d', 'Ubuntu-24.04', '-u', 'root', '--', 'systemctl', 'start', 'guacd'],
            { detached: true, stdio: 'ignore', windowsHide: true }).unref();
    } catch (e) { /* 守柔 */ }
    const dir = daoWinTunnelDir();
    if (!dir) return { error: '未找到 guacamole-lite 隧道(设 DAO_TUNNEL_DIR 或置于 C:/dao_vm/guactunnel; 需先 npm install)' };
    try {
        const start = path.join(dir, 'start.ps1');
        const tunnelEnv = Object.assign({}, process.env, { DAO_ACCOUNTS_JSON: daoWinGuacAcctPath() });
        if (fs.existsSync(start)) {
            cp.spawn('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', start],
                { detached: true, stdio: 'ignore', windowsHide: true, env: tunnelEnv }).unref();
        } else {
            cp.spawn(process.execPath, ['server.js'], {
                cwd: dir, detached: true, stdio: 'ignore', windowsHide: true,
                env: Object.assign({}, tunnelEnv, { ELECTRON_RUN_AS_NODE: '1' })
            }).unref();
        }
    } catch (e) { return { error: '隧道启动失败: ' + String(e && e.message || e) }; }
    let up = false;
    for (let i = 0; i < 24 && !up; i++) { await new Promise((r) => setTimeout(r, 250)); up = await daoTcpUp(DAO_TUNNEL_HTTP_PORT); }
    if (!up) return { error: '隧道未在 127.0.0.1:' + DAO_TUNNEL_HTTP_PORT + ' 起来(检查 guacd/node/依赖)' };
    return ret;
}
// ── 模块② 账号池宿主原语(多 Windows 账号生命周期 · 对齐 core/accounts.py 语义 · 不落盘口令) ──
// New-LocalUser + Remote Desktop Users(建号) / quser(会话态) / logoff(注销) / Remove-LocalUser(删号)。
// 注册表 ~/.dao/accounts.json 仅存 hostname/port/username/admin(无口令); 口令仅瞬时传给 PowerShell。
function daoWinAcctDir() {
    const d = path.join(os.homedir(), '.dao');
    try { fs.mkdirSync(d, { recursive: true, mode: 0o700 }); } catch (e) { /* 守柔 */ }
    return d;
}
// 专用注册表: 绝不复用 ~/.dao/accounts.json(那是 Devin 登录态账号池 · 复用会污染账号列并在写入时覆盖其 token 存储)。
function daoWinAcctRegPath() { return path.join(daoWinAcctDir(), 'win-rdp-accounts.json'); }
function daoWinAcctReg() {
    try {
        const j = JSON.parse(fs.readFileSync(daoWinAcctRegPath(), 'utf8'));
        if (!j || typeof j !== 'object' || Array.isArray(j)) return {};
        // 守柔: 仅收 value 为对象的条目(标量键如 token/activeAccount 一律忽略, 防误读非本表 JSON)。
        const reg = {};
        for (const k of Object.keys(j)) { if (j[k] && typeof j[k] === 'object' && !Array.isArray(j[k])) reg[k] = j[k]; }
        return reg;
    } catch (e) { return {}; }
}
function daoWinAcctRegSave(reg) {
    try { fs.writeFileSync(daoWinAcctRegPath(), JSON.stringify(reg, null, 2), 'utf8'); } catch (e) { /* 守柔 */ }
}
function daoWinAcctNameOk(n) { return /^[A-Za-z0-9][A-Za-z0-9._-]{0,19}$/.test(n || ''); }
function daoPSQuote(s) { return "'" + String(s).replace(/'/g, "''") + "'"; }
function daoPS(script) {
    try {
        const cp = require('child_process');
        const r = cp.spawnSync('powershell', ['-NoProfile', '-NonInteractive', '-Command', script], { encoding: 'utf8', timeout: 60000 });
        return { rc: (r.status === null || r.status === undefined) ? 1 : r.status, out: (r.stdout || '').trim(), err: (r.stderr || '').trim() };
    } catch (e) { return { rc: 127, out: '', err: String(e && e.message || e) }; }
}
function daoParseQuser(out) {
    const map = {};
    if (!out) return map;
    const lines = out.split(/\\r?\\n/).filter((l) => l.trim());
    for (let i = 1; i < lines.length; i++) {
        const parts = lines[i].replace(/^>/, '').trim().split(/\\s+/);
        if (!parts.length) continue;
        const uname = parts[0];
        let sid = null, state = null;
        for (let j = 1; j < parts.length; j++) {
            if (/^\\d+$/.test(parts[j])) { sid = parts[j]; state = parts[j + 1] || null; break; }
        }
        map[uname.toLowerCase()] = { id: sid, state: state };
    }
    return map;
}
function daoWinAcctList() {
    if (process.platform !== 'win32') return [];
    const reg = daoWinAcctReg();
    const sess = daoParseQuser(daoPS('quser 2>$null').out);
    const names = [], seen = {};
    const gl = daoPS('Get-LocalUser | Where-Object {$_.Enabled -eq $true} | Select-Object -ExpandProperty Name');
    gl.out.split(/\\r?\\n/).forEach((l) => { l = l.trim(); if (l && !seen[l.toLowerCase()]) { seen[l.toLowerCase()] = 1; names.push(l); } });
    Object.keys(reg).forEach((n) => { if (!seen[n.toLowerCase()]) { seen[n.toLowerCase()] = 1; names.push(n); } });
    return names.map((n) => {
        const r = reg[n] || {};
        return {
            name: n, admin: !!r.admin, managed: !!reg[n],
            target: { hostname: r.hostname || '127.0.0.1', port: r.port || '3389' },
            session: sess[n.toLowerCase()] || null,
        };
    });
}
function daoWinAcctCreate(name, password, admin) {
    if (process.platform !== 'win32') return { error: '账号管理仅 Windows 本机可用' };
    if (!daoWinAcctNameOk(name)) return { error: '非法账号名(限字母数字与 . _ - , ≤20): ' + name };
    const pw = password || 'Dao@2026!';
    const script = [
        "$ErrorActionPreference='Stop'",
        '$pw = ConvertTo-SecureString ' + daoPSQuote(pw) + ' -AsPlainText -Force',
        '$u = Get-LocalUser -Name ' + daoPSQuote(name) + ' -ErrorAction SilentlyContinue',
        'if ($null -eq $u) { New-LocalUser -Name ' + daoPSQuote(name) + ' -Password $pw -PasswordNeverExpires -AccountNeverExpires | Out-Null }',
        'else { Set-LocalUser -Name ' + daoPSQuote(name) + ' -Password $pw }',
        "Add-LocalGroupMember -Group 'Remote Desktop Users' -Member " + daoPSQuote(name) + ' -ErrorAction SilentlyContinue',
        (admin ? "Add-LocalGroupMember -Group 'Administrators' -Member " + daoPSQuote(name) + ' -ErrorAction SilentlyContinue' : ''),
        "Write-Output 'OK'",
    ].join('\\n');
    const r = daoPS(script);
    if (r.rc !== 0) return { error: (r.err || r.out || ('rc=' + r.rc)) };
    const reg = daoWinAcctReg();
    reg[name] = { hostname: '127.0.0.1', port: '3389', username: name, admin: !!admin };
    daoWinAcctRegSave(reg);
    return { ok: true, name: name };
}
function daoWinAcctDestroy(name) {
    if (process.platform !== 'win32') return { error: '账号管理仅 Windows 本机可用' };
    if (!daoWinAcctNameOk(name)) return { error: '非法账号名: ' + name };
    const script = [
        "$ErrorActionPreference='SilentlyContinue'",
        '$q = quser 2>$null',
        'if ($q) { $q | Select-Object -Skip 1 | ForEach-Object {',
        "  $cols = ($_ -replace '^>','').Trim() -split '\\\\s+'",
        '  if ($cols[0] -ieq ' + daoPSQuote(name) + ') {',
        "    $sid = ($cols | Where-Object { $_ -match '^\\\\d+$' } | Select-Object -First 1)",
        '    if ($sid) { logoff $sid }',
        '  } } }',
        'Remove-LocalUser -Name ' + daoPSQuote(name) + ' -ErrorAction SilentlyContinue',
        "Get-CimInstance Win32_UserProfile | Where-Object { $_.LocalPath -like ('*\\\\' + " + daoPSQuote(name) + ') } | Remove-CimInstance -ErrorAction SilentlyContinue',
        "Write-Output 'OK'",
    ].join('\\n');
    const r = daoPS(script);
    const reg = daoWinAcctReg();
    if (reg[name]) { delete reg[name]; daoWinAcctRegSave(reg); }
    if (r.rc !== 0) return { error: (r.err || r.out || ('rc=' + r.rc)) };
    return { ok: true, name: name };
}
function daoWinAcctLogoff(id) {
    if (process.platform !== 'win32') return { error: '账号管理仅 Windows 本机可用' };
    const sid = parseInt(id, 10);
    if (!Number.isFinite(sid)) return { error: '非法会话 ID: ' + id };
    const r = daoPS('logoff ' + sid);
    if (r.rc !== 0 && r.err) return { error: r.err };
    return { ok: true };
}
`;

const HOST_CASES = `            // ── dao-one-windows · 🪟 Windows 板块(RDP 档案管理 · 官方 mstsc 收编) ──
            case 'winRdpList': {
                reply({ type: 'winRdpData', items: daoWinRdpList() });
                break;
            }
            case 'winRdpSave': {
                const r = daoWinRdpSave(msg.profile || {});
                if (r && r.error) reply({ type: 'error', msg: r.error });
                reply({ type: 'winRdpData', items: daoWinRdpList(), reset: true });
                break;
            }
            case 'winRdpDel': {
                daoWinRdpDel(msg.name);
                reply({ type: 'winRdpData', items: daoWinRdpList(), reset: true });
                break;
            }
            case 'winRdpConnect': {
                const r = daoWinRdpConnect(msg.name);
                if (r && r.error) reply({ type: 'error', msg: r.error });
                else reply({ type: 'actionResult', command: 'winRdpConnect', ok: true });
                break;
            }
            case 'winRdpOpenDir': {
                try { await vscode.env.openExternal(vscode.Uri.file(daoWinRdpDir())); } catch (e) { /* 守柔 */ }
                reply({ type: 'actionResult', command: 'winRdpOpenDir', ok: true });
                break;
            }
            case 'winDeskEnsure': {
                const r = await daoWinDeskEnsure({ account: msg.account, label: msg.label, target: msg.target });
                reply(Object.assign({ type: 'winDeskReady' }, r || {}));
                break;
            }
            case 'winDeskOpenExternal': {
                // 兑底: 外壳(/shell 顶层页面栏)不在时, 退而交给系统浏览器开同一张独立桌面页。
                try { if (msg.url) await vscode.env.openExternal(vscode.Uri.parse(String(msg.url))); } catch (e) { /* 守柔 */ }
                reply({ type: 'actionResult', command: 'winDeskOpenExternal', ok: true });
                break;
            }
            // ── 模块② 账号池(多 Windows 账号生命周期) ──
            case 'winAcctList': {
                reply({ type: 'winAcctData', items: daoWinAcctList() });
                break;
            }
            case 'winAcctCreate': {
                const r = daoWinAcctCreate(msg.name, msg.password, msg.admin);
                if (r && r.error) reply({ type: 'error', msg: r.error });
                reply({ type: 'winAcctData', items: daoWinAcctList() });
                break;
            }
            case 'winAcctDestroy': {
                const r = daoWinAcctDestroy(msg.name);
                if (r && r.error) reply({ type: 'error', msg: r.error });
                reply({ type: 'winAcctData', items: daoWinAcctList() });
                break;
            }
            case 'winAcctLogoff': {
                const r = daoWinAcctLogoff(msg.id);
                if (r && r.error) reply({ type: 'error', msg: r.error });
                reply({ type: 'winAcctData', items: daoWinAcctList() });
                break;
            }
`;

const NOAUTH_ADD = "'winRdpList', 'winRdpSave', 'winRdpDel', 'winRdpConnect', 'winRdpOpenDir', 'winDeskEnsure', 'winDeskOpenExternal', 'winAcctList', 'winAcctCreate', 'winAcctDestroy', 'winAcctLogoff'";

module.exports = { FRONTEND_JS, HOST_HELPERS, HOST_CASES, NOAUTH_ADD };
