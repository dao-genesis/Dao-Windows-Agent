# agentctl（vendored · AI GUI 操作底座）

本目录是从 **devin-remote** 仓库 `cloud/vm-replica/agentctl/` 原样收编（vendor）的
**依赖零安装（纯 stdlib + 可选 numpy）** GUI 操作底座——语义优先（UIA/AT-SPI 控件树）、
像素兜底（截图 + locate/template/fovea），Windows 与 Linux/X11 双地一套词汇。

- 上游仓库：`devin-remote`
- 上游路径：`cloud/vm-replica/agentctl/`
- 上游提交：`aa6aa60198ac509ead60da05f8c8e36a7aae62a6`
- 收编文件：`osctl.py` `_osbackend_win.py` `_osbackend_x11.py` `_uia_win.py` `cdp.py` `browser.py`
  （测试/演示/fixture 未收编；`JOURNAL.md` 因体积过大未收编，缘由见上游 README）

## 为何 vendor 而非引用

本仓 `core/` 会随冷启动应答盘整体带入 guest（见 `coldstart/windows-sim/scripts/firstlogon.ps1`
把 `core/` 复制进 `C:\dao_win`），故把底座放在 `core/gui/agentctl/` 即随插件本体
零配置抵达 guest，无需 guest 内再 clone/pip。這正合「整合進插件一切的底層」之意。

## 接入方式（不改上游·薄绑定）

上游模块用**平铺 import**（`import _osbackend_win as _be`、`from cdp import CDP`），
按其设计需把本目录置于 `sys.path`。故本仓不改上游源码（避免漂移），而由
`core/adapter/osctl_driver.py` 在导入前把本目录挂上 `sys.path`，再 `import osctl`。
osctl 在导入期按 `sys.platform` 选后端（Win→UIA、Linux→X11），故仅在 guest（Windows）
或带 X 的 Linux 上可实机运行；Linux/CI 无对应库时导入即失败——驱动层据此优雅退回
dry-run，纯逻辑仍可单测（见 `tests/test_osctl_driver.py`，以假 osctl 注入验证翻译逻辑）。

## 语义优先铁律（彻底规避「截图+点击」低能操作）

绑定层把级别② UIA 计划、级别③ 视觉计划统一落到 osctl：
- 先按 `target_hint` 走 `uia_find`（Name/AutomationId/HelpText 命中）→ 取控件 rect → 在其自报几何点击/置值（精确、Unicode 安全）；
- 仅当语义地板抓不到时才降级像素：`locate`/`find_color`/`template`/`reach` 视觉求解坐标。

坐标永远是最后手段——与本仓三级回退铁律同源。
