#!/usr/bin/env bash
# 取 Windows 安装介质 + virtio 驱动。
#   --eval win11|win10 : 拉官方评估版 ISO（企业版，无需密钥，最适合可复现自动化）
#   （家庭/教育/专业版：用户把自带 ISO 放到 media/ 下，命名 <edition>.iso）
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
MEDIA="$HERE/media"; mkdir -p "$MEDIA"

# 微软官方评估中心（Evaluation Center）：fwlink 稳定入口 → 302 直达当期评估版 ISO
# （实测无需表单/许可页即可解析；若 fwlink 失效再回落到评估中心页面人工获取）。
EVAL_FWLINK_WIN11="https://go.microsoft.com/fwlink/?linkid=2289031"   # Win11 Ent Eval x64 en-us
EVAL_PAGE_WIN11="https://www.microsoft.com/en-us/evalcenter/download-windows-11-enterprise"
EVAL_FWLINK_WIN10="https://go.microsoft.com/fwlink/p/?LinkID=2208844" # Win10 Ent Eval x64 en-us
EVAL_PAGE_WIN10="https://www.microsoft.com/en-us/evalcenter/download-windows-10-enterprise"
# virtio-win 稳定驱动（KVM 下 Windows 磁盘/网卡/显卡/qemu-ga 必备）
VIRTIO_URL="https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/virtio-win.iso"

valid_iso() {
  [ -s "$1" ] && isoinfo -d -i "$1" >/dev/null 2>&1
}

fetch_iso() {
  local url="$1" dest="$2" label="$3" part="${2}.part"
  if valid_iso "$dest"; then
    echo "$label 已存在且校验通过，跳过下载"
    return
  fi
  if [ -f "$dest" ]; then
    mv -f "$dest" "$part"
    echo "$label 不完整，转为断点文件继续下载"
  fi
  echo "== 拉取 $label: $url =="
  if curl -fL --retry 3 -C - -o "$part" "$url" && valid_iso "$part"; then
    mv -f "$part" "$dest"
    echo "$label 就绪"
  else
    echo "$label 下载或 ISO 校验失败（保留 $part 供下次断点续传）"
    return 1
  fi
}

mode="${1:-}"; target="${2:-win11}"
if [ "$mode" = "--eval" ]; then
  fw="EVAL_FWLINK_${target^^}"; fw="${!fw:-}"
  page="EVAL_PAGE_${target^^}"; page="${!page:-}"
  [ -z "$page" ] && { echo "未知评估目标: $target (win11|win10)"; exit 1; }
  if valid_iso "$MEDIA/${target}.iso"; then
    echo "${target}.iso 已存在且校验通过，跳过下载"
  else
    loc="$(curl -sI "$fw" | tr -d '\r' | awk 'tolower($1)=="location:"{print $2}' | head -1)"
    if echo "$loc" | grep -qiE '\.iso(\?|$)'; then
      fetch_iso "$loc" "$MEDIA/${target}.iso" "官方评估版 ${target}.iso"
    else
      echo "fwlink 未解析到 ISO 直链，请从评估中心手动获取(需接受许可):"
      echo "  $page"
      echo "下载后放到: $MEDIA/${target}.iso"
    fi
  fi
fi

echo "== 拉取 virtio-win 驱动 ISO =="
fetch_iso "$VIRTIO_URL" "$MEDIA/virtio-win.iso" "virtio-win.iso"

echo
echo "现有介质:"; ls -lh "$MEDIA" 2>/dev/null || true
echo "提示：家庭/教育/专业版把自带 ISO 命名为 <edition>.iso 放入 $MEDIA/ 即可被 build_image.sh 选用。"
