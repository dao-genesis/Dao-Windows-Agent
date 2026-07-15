"""单账号多分身（clone）隔离本源。

一个 Windows 账号可复制多路 RDP 会话（分身）。RDP 会话层已互相隔离（各自 termsrv
会话、各自 explorer），但**同账号的应用层单实例锁是 per-user、不是 per-session**：
VS Code / Devin Desktop（Electron）等在共享 `%APPDATA%` 里放单实例锁/命名管道，
第二个分身启动同一软件时会被第一个分身的实例吞掉——窗口开到了错误的会话里，
表象即"两个分身开同一软件互相缠绕、无法隔离操作"。

本模块给出**零配置的应用层分身隔离**：按分身号派生独立的 user-data/profile 目录，
令单实例锁的作用域从"每账号"收窄到"每分身"，从而鸡犬相闻、老死不相往来。
纯逻辑、可在 Linux/CI 离线单测；guest 内由 `dao-clone-open.ps1` 落地执行。
"""
from core.clone.app_isolation import (
    ISOLATION_REGISTRY,
    CloneLaunchSpec,
    build_clone_launch,
    clone_data_root,
    isolatable_apps,
)

__all__ = [
    "ISOLATION_REGISTRY",
    "CloneLaunchSpec",
    "build_clone_launch",
    "clone_data_root",
    "isolatable_apps",
]
