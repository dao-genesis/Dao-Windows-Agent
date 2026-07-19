"""RdpTarget · 真机已有的 RDP 回环目标发现与分配。

道法自然 · 无为而无不为。真机 DESKTOP-MASTER 实证：每个账号映射一个专属 127.0.0.x，
.rdp 文件与 Credential Manager 各存一份 → mstsc /v:127.0.0.x 即免提示直登。

本模块只读发现这些已有映射，并为新账号分配下一个可用回环地址：
  · 解析桌面上的 .rdp 文件（`full address:s:127.0.0.x`）
  · 解析 cmdkey /list 中的 TERMSRV/127.0.0.x 条目
  · 合并为 account→RdpTarget 映射
  · 为新账号分配下一个空闲 127.0.0.x

可注入 runner → Linux/CI 纯逻辑可测。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from core.adapter.subprocess_api import decode_output
import subprocess

Runner = Callable[["list[str]"], "tuple[int, str, str]"]

_LOOPBACK_RE = re.compile(r"^127\.0\.0\.(\d{1,3})$")
_RDP_ADDR_RE = re.compile(r"^full address:s:(.+)$", re.MULTILINE | re.IGNORECASE)
_RDP_USER_RE = re.compile(r"^username:s:(.+)$", re.MULTILINE | re.IGNORECASE)
_CMDKEY_TARGET_RE = re.compile(r"TERMSRV/(127\.0\.0\.\d+)")
_CMDKEY_USER_RE = re.compile(r"User:\s*(.+)")
_DEFAULT_PORT = 3389
_LOOPBACK_START = 2  # .1 reserved for console/Administrator
_LOOPBACK_MAX = 254


def _default_runner(argv: "list[str]") -> "tuple[int, str, str]":
    try:
        proc = subprocess.run(argv, capture_output=True, timeout=30)
    except FileNotFoundError:
        return 127, "", f"{argv[0]} not available"
    return proc.returncode, decode_output(proc.stdout), decode_output(proc.stderr)


@dataclass
class RdpTarget:
    """一路回环目标的完整描述。"""
    username: str
    loopback_ip: str
    port: int = _DEFAULT_PORT
    rdp_file: str = ""
    has_credential: bool = False

    @property
    def loopback_index(self) -> int:
        m = _LOOPBACK_RE.match(self.loopback_ip)
        return int(m.group(1)) if m else -1

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "loopback_ip": self.loopback_ip,
            "port": self.port,
            "rdp_file": self.rdp_file,
            "has_credential": self.has_credential,
            "loopback_index": self.loopback_index,
        }


@dataclass
class RdpTargetRegistry:
    """真机已有 RDP 回环目标发现 + 新目标分配。只读发现，不改机器。"""
    runner: Runner = _default_runner
    rdp_search_dirs: "list[str]" = field(default_factory=list)

    def discover(self) -> dict:
        """只读发现真机上已有的 account→loopback 映射。合并 .rdp 文件 + cmdkey。

        以**回环 IP** 为主键合并（一 IP 一目标），避免同名账号占多路回环时丢目标——
        真机 DESKTOP-MASTER 上 Administrator 同时持有 127.0.0.1 与 127.0.0.20。
        """
        rdp_targets = self._parse_rdp_files()
        cred_targets = self._parse_cmdkey()
        # 合并：按回环 IP 主键，.rdp 文件为主（含 rdp_file 路径），cmdkey 补充 has_credential
        merged: dict[str, RdpTarget] = {}
        for t in rdp_targets:
            merged[t.loopback_ip] = t
        for ip, user in cred_targets.items():
            if ip in merged:
                merged[ip].has_credential = True
            else:
                merged[ip] = RdpTarget(
                    username=user, loopback_ip=ip,
                    has_credential=True)
        targets = list(merged.values())
        used_ips = {t.loopback_ip for t in targets}
        return {
            "ok": True,
            "targets": [t.to_dict() for t in targets],
            "used_loopback_ips": sorted(used_ips),
            "next_available_index": self._next_free_index(used_ips),
        }

    def find_target(self, username: str) -> Optional[RdpTarget]:
        """按账号名查找已有目标。"""
        result = self.discover()
        for t in result.get("targets", []):
            if t["username"].lower() == (username or "").lower():
                return RdpTarget(**{k: v for k, v in t.items()
                                   if k != "loopback_index"})
        return None

    def allocate_loopback(self, username: str) -> str:
        """为新账号分配下一个可用 127.0.0.x。"""
        result = self.discover()
        idx = result.get("next_available_index", _LOOPBACK_START)
        return f"127.0.0.{idx}"

    def _next_free_index(self, used_ips: set) -> int:
        used_indices = set()
        for ip in used_ips:
            m = _LOOPBACK_RE.match(ip)
            if m:
                used_indices.add(int(m.group(1)))
        for i in range(_LOOPBACK_START, _LOOPBACK_MAX + 1):
            if i not in used_indices:
                return i
        return _LOOPBACK_MAX + 1

    def _parse_rdp_files(self) -> "list[RdpTarget]":
        targets = []
        for d in self._search_dirs():
            if not os.path.isdir(d):
                continue
            for f in os.listdir(d):
                if not f.lower().endswith(".rdp"):
                    continue
                path = os.path.join(d, f)
                t = _parse_one_rdp(path)
                if t:
                    targets.append(t)
        return targets

    def _search_dirs(self) -> "list[str]":
        dirs = list(self.rdp_search_dirs)
        # Default: common desktop paths
        for env in ("USERPROFILE", "PUBLIC"):
            base = os.environ.get(env, "")
            if base:
                dirs.append(os.path.join(base, "Desktop"))
        return dirs

    def _parse_cmdkey(self) -> "dict[str, str]":
        """解析 cmdkey /list 输出，提取 TERMSRV/127.0.0.x → username 映射。"""
        rc, out, _ = self.runner(["cmdkey", "/list"])
        if rc != 0 or not out:
            return {}
        mapping: dict[str, str] = {}
        lines = out.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            m = _CMDKEY_TARGET_RE.search(line)
            if m:
                ip = m.group(1)
                # Look for User: in next few lines
                for j in range(i + 1, min(i + 5, len(lines))):
                    um = _CMDKEY_USER_RE.match(lines[j].strip())
                    if um:
                        mapping[ip] = um.group(1).strip()
                        break
            i += 1
        return mapping


def _parse_one_rdp(path: str) -> Optional[RdpTarget]:
    """解析单个 .rdp 文件，提取回环地址和用户名。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return None
    addr_m = _RDP_ADDR_RE.search(content)
    if not addr_m:
        return None
    addr = addr_m.group(1).strip()
    if not _LOOPBACK_RE.match(addr):
        return None
    user_m = _RDP_USER_RE.search(content)
    username = user_m.group(1).strip() if user_m else ""
    if not username:
        # Derive from filename: RDP_ai.rdp → ai
        base = os.path.splitext(os.path.basename(path))[0]
        if base.upper().startswith("RDP_"):
            username = base[4:]
    return RdpTarget(
        username=username, loopback_ip=addr,
        rdp_file=path) if username else None


__all__ = ["RdpTarget", "RdpTargetRegistry"]
