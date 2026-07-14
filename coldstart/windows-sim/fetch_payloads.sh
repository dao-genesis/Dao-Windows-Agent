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

# Mesa3D 软件 OpenGL（llvmpipe）：QEMU 虚拟显示器只报 "Microsoft Basic Display Adapter"，
# 无 OpenGL 2.0，FreeCAD/带 3D 视口的软件启动即崩（"requires OpenGL 2.0"）。把 Mesa 的
# opengl32.dll(ICD 垫片)+libgallium_wgl.dll(llvmpipe 驱动)+dxil.dll 就近放到 FreeCAD\bin，
# 即得纯软件 OpenGL 4.5，零 GPU 依赖。此处在宿主(有 7z)解出三件 DLL 落缓存，随盘带入 guest。
fetch_mesa() {
  local out7z="$PAY/mesa.7z"
  local need=("mesa_opengl32.dll" "mesa_libgallium_wgl.dll" "mesa_dxil.dll")
  local have=1; for f in "${need[@]}"; do [ -s "$PAY/$f" ] || have=0; done
  if [ "$have" = 1 ]; then echo "  [OK] Mesa 三件 DLL 已缓存"; return 0; fi
  # GitHub API 匿名限流（60次/h·共享出口 IP 下 403 常态）——有 token 则带上；查询失败退钉住版。
  local auth=(); [ -n "${GITHUB_TOKEN:-${GH_TOKEN:-}}" ] && auth=(-H "Authorization: Bearer ${GITHUB_TOKEN:-${GH_TOKEN:-}}")
  local url
  url="$(curl -fsSL --retry 3 "${auth[@]}" 'https://api.github.com/repos/pal1000/mesa-dist-win/releases/latest' 2>/dev/null \
        | grep -oE '"browser_download_url": *"[^"]*release-msvc\.7z"' | head -1 | grep -oE 'https[^"]*')"
  if [ -z "$url" ]; then
    # 钉住版兜底：release 资产直链不走 API，不受 API 限流影响。
    url='https://github.com/pal1000/mesa-dist-win/releases/download/24.3.2/mesa3d-24.3.2-release-msvc.7z'
    echo "  [..] Mesa 版本查询失败（API 限流/离线），改用钉住版 24.3.2"
  fi
  echo "  [..] 拉取 Mesa: $url"
  curl -fL --retry 3 -o "$out7z" "$url" || { echo "  [--] Mesa 下载失败"; return 1; }
  local ex="$PAY/.mesa_extract"; rm -rf "$ex"; mkdir -p "$ex"
  if command -v 7z >/dev/null 2>&1; then 7z x -y -o"$ex" "$out7z" >/dev/null 2>&1
  elif command -v 7za >/dev/null 2>&1; then 7za x -y -o"$ex" "$out7z" >/dev/null 2>&1
  else echo "  [--] 无 7z，无法解出 Mesa DLL"; return 1; fi
  cp -f "$ex/x64/opengl32.dll"        "$PAY/mesa_opengl32.dll"        2>/dev/null || rc=1
  cp -f "$ex/x64/libgallium_wgl.dll"  "$PAY/mesa_libgallium_wgl.dll"  2>/dev/null || rc=1
  cp -f "$ex/x64/dxil.dll"            "$PAY/mesa_dxil.dll"            2>/dev/null || rc=1
  rm -rf "$ex" "$out7z"
  for f in "${need[@]}"; do [ -s "$PAY/$f" ] && echo "  [OK] $f 就绪 ($(du -h "$PAY/$f" | cut -f1))"; done
}
fetch_mesa || rc=1
echo "现有载荷:"; ls -lh "$PAY" 2>/dev/null || true
exit $rc
