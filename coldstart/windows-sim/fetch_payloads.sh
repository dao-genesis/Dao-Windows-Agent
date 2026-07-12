#!/usr/bin/env bash
# 预下载 guest 置备载荷到宿主缓存 media/payloads/（吸收 devin-remote 冷启动思路：
# 装机载荷一次下载、多次装机复用；guest 首登优先取随盘缓存，零重复下载、离线可装）。
# 幂等：已存在且非空即跳过；支持断点续传（.part）。单项失败不阻断其余（装机时在线兜底仍在）。
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PAY="$HERE/media/payloads"; mkdir -p "$PAY"

fetch() {
  local name="$1" url="$2" dest="$PAY/$1" part="$PAY/$1.part"
  if [ -s "$dest" ]; then echo "  [OK] $name 已缓存 ($(du -h "$dest" | cut -f1))"; return 0; fi
  echo "  [..] 拉取 $name: $url"
  if curl -fL --retry 3 -C - -o "$part" "$url" && [ -s "$part" ]; then
    mv -f "$part" "$dest"; echo "  [OK] $name 就绪 ($(du -h "$dest" | cut -f1))"
  else
    echo "  [--] $name 下载失败（保留 $part 供断点续传；guest 首登会在线兜底）"
    return 1
  fi
}

echo "== 预下载 guest 置备载荷（media/payloads/ 宿主缓存）=="
rc=0
fetch vc_redist.x64.exe 'https://aka.ms/vs/17/release/vc_redist.x64.exe' || rc=1
fetch py312.exe 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' || rc=1
fetch VSCodeSetup.exe 'https://update.code.visualstudio.com/latest/win32-x64/stable' || rc=1
fetch DevinUserSetup.exe 'https://windsurf.com/api/windsurf/download-redirect?build=win32-x64-user&isNext=false' || rc=1
fetch RDPWrap.zip 'https://github.com/stascorp/rdpwrap/releases/download/v1.6.2/RDPWrap-v1.6.2.zip' || rc=1
fetch rdpwrap_community.ini 'https://raw.githubusercontent.com/sebaxakerhtc/rdpwrap.ini/master/rdpwrap.ini' || rc=1
# 领域软件本体（大件·全离线装机）：guest 常无外网/winget，缺缓存即装不上（真机踩坑）
fetch FreeCAD-setup.exe 'https://github.com/FreeCAD/FreeCAD/releases/download/1.0.0/FreeCAD_1.0.0-conda-Windows-x86_64-installer-1.exe' || rc=1
fetch KiCad-setup.exe 'https://kicad-downloads.s3.cern.ch/windows/stable/kicad-8.0.9-x86_64.exe' || rc=1
echo "现有载荷:"; ls -lh "$PAY" 2>/dev/null || true
exit $rc
