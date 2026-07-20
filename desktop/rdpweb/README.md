# desktop/rdpweb · 官方 RDP 协议 → 归一单网页(Windows 原生·零 Docker/guacd)

> 反者道之动:不自造交互体系,直接把 **Windows 官方终端服务(RDP·3389)** 的桌面本体
> 经协议客户端(`node-rdpjs`)搬进 IDE 归一单网页的 `<canvas>`;鼠标/键盘/滚轮走
> **官方 RDP 输入 PDU**,原生拖拽所见即所得。我们不生产水,只做官方协议的搬运工。

## 与 `desktop/tunnel`(guacd 路线)的关系
- `desktop/tunnel`:WebSocket ↔ **guacd** ↔ RDP,需要 guacd(Docker/Linux),重。
- `desktop/rdpweb`(本目录):WebSocket ↔ **node-rdpjs**(纯 Node)↔ RDP,**零 Docker/guacd**,
  在用户 Windows 真机原生可跑。二者都是「原生远程桌面协议级路由」,非截图推流。

## 架构
```
IDE 归一单网页(/shell 内 <canvas> + rle.js 解压)
        ↓ WebSocket(/ws · JSON: infos/mouse/wheel/scancode ; bitmap base64)
gateway.js(node-rdpjs 协议客户端 · 服务端持有凭据)
        ↓ 官方 RDP(3389 · 标准/TLS 安全层)
Windows 会话(同一主账号多路 = 分身;各自独立会话,共享同一份软件/数据/资源)
```

## 主账号分身模型
同一 Windows 账号连多路 loopback 别名(`127.0.0.1`/`127.0.0.2`…),在
`fSingleSessionPerUser=0`(允许同账号多会话)下,每次登录 = 该账号一路**独立会话**:
- 共享:已安装软件、用户目录、AppData、注册表 HKCU、登录态(同一 profile);
- 独立:桌面对象、输入队列、运行实例 → 天然隔离,互不串扰;
- 单实例互斥体(如微信/QQ)跨会话的冲突行为即在此模型下暴露并迭代。

## 运行
```powershell
cd desktop\rdpweb
npm install                       # node-rdpjs-2 + ws
powershell -File .\fetch-client-assets.ps1   # 取 mstsc.js 客户端资产(GPLv3·见下)
# 凭据(服务端持有,不下发浏览器):
#   C:\ProgramData\dao_vm\rdp_cred.json = {"username":"<acct>","password":"<pwd>","domain":""}
node gateway.js                   # 监听 127.0.0.1:9250
```
然后在归一网页(/shell)内新开子页 `http://127.0.0.1:9250`。

## 前置(用户真机·官方 RDP)
- 终端服务开启、3389 监听;同账号多会话需 `fSingleSessionPerUser=0`(RDPWrap 或组策略)。
- `node-rdpjs` 走标准/TLS 安全层;若启用 NLA/CredSSP(`UserAuthentication=1`)需另行适配。

## 诚实边界(待迭代)
- **剪贴板/文件拖拽跨会话重定向**(RDP `cliprdr`/`rdpdr` 虚拟通道)`node-rdpjs` 未实现——
  桌面内原生拖拽可用,跨分身的剪贴板/拖放需补虚拟通道或走控制面 `clipboard_*` 原语兜底。
- bitmap 走 base64/JSON,后续可改二进制帧降开销。
- GPU 独占渲染软件在 RDP 会话下的表现依 Windows 固有约束。

## 许可
`gateway.js`、`client/client_ws.js`、`client/grid.html` 为本仓原创。
`client/{rle.js,keyboard.js,mstsc.js,canvas.js}` 来自 [citronneur/mstsc.js](https://github.com/citronneur/mstsc.js)(**GPLv3**),
**不纳入本仓**,由 `fetch-client-assets.ps1` 运行期获取,遵循其 GPLv3 许可。
