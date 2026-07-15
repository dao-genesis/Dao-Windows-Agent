@echo off
rem Dao specialize 兜底：把 firstlogon.ps1 从应答盘落到 C:\，并装 SetupComplete.cmd
rem （安装收尾 SYSTEM 必跑，与 FirstLogonCommands 双保险；firstlogon 自带 .provisioned 幂等门）。
rem %~dp0 = 本脚本所在盘根（应答盘），免盘符猜测。
copy /y "%~dp0firstlogon.ps1" C:\dao-firstlogon-media.ps1 >nul 2>&1
if not exist C:\Windows\Setup\Scripts mkdir C:\Windows\Setup\Scripts
> C:\Windows\Setup\Scripts\SetupComplete.cmd echo powershell -ExecutionPolicy Bypass -NoProfile -File C:\dao-firstlogon-media.ps1 ^>^> C:\dao-setupcomplete.log 2^>^&1
