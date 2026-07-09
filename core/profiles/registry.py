"""应用画像注册表 + 动词发现（移植 ha-copilot 的 search_tools/describe 配方）。

agent 通过 search_verbs 找能力、describe_app 看细节，再 invoke——
与 ha-copilot 的 search_tools/describe_tool 同构，只是从"HA 工具"泛化到"任意软件动词"。
"""
from __future__ import annotations

import re
from typing import Callable, Optional

from core.adapter.base import AppAdapter
from core.profiles.schema import AppProfile

_WORD = re.compile(r"[a-z0-9]+")
_CJK = re.compile(r"[\u4e00-\u9fff]")


def _tokens(text: str) -> set[str]:
    """词元化：拉丁词 + CJK 字（unigram）+ CJK 相邻二元（bigram）。

    中文无空格分词，故对汉字取单字 + 相邻二字组合——兼顾召回(单字)与精度(二字)，
    使纯中文查询（本项目主语言）也能命中动词，无需外部分词器（守纯 stdlib 底座）。
    """
    low = text.lower()
    toks: set[str] = set(_WORD.findall(low))
    cjk = _CJK.findall(low)
    toks.update(cjk)
    toks.update(a + b for a, b in zip(cjk, cjk[1:]))
    return toks


# 中英同义桥（板块四·语义检索强化）：查询词元 → 画像侧惯用词元。
# 画像动词/摘要多为英文动词名 + 中文摘要，纯中文查询靠此桥命中英文动词名，
# 反向亦然。守纯 stdlib：小而准的领域同义表，不引外部词典/向量库。
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "导出": ("export", "output"),
    "导入": ("import",),
    "建模": ("model", "modeling", "macro", "step", "stl"),
    "网格": ("mesh", "stl"),
    "原理图": ("schematic", "sch"),
    "制造": ("gerber", "fab", "drill"),
    "钻孔": ("drill",),
    "截图": ("screenshot", "capture"),
    "打开": ("open", "launch", "start"),
    "关闭": ("close", "quit", "shutdown"),
    "运行": ("run", "exec"),
    "执行": ("run", "exec", "invoke"),
    "检查": ("inspect", "check", "verify"),
    "版本": ("version",),
    "文件": ("file",),
    "读取": ("read", "get"),
    "写入": ("write", "set"),
    "搜索": ("search", "find"),
    "自动化": ("automation",),
    "智能家居": ("homeassistant", "ha", "smart", "home"),
    "灯": ("light",),
    "服务": ("service", "call"),
    "实体": ("entity", "states", "state"),
    "浏览器": ("browser", "chrome", "cdp"),
    "进程": ("process", "proc", "ps"),
    "窗口": ("window",),
    "输入": ("type", "input", "key"),
    "点击": ("click",),
    "gerber": ("export_gerbers", "fab"),
    "stl": ("mesh", "export_stl"),
    "step": ("export_step",),
    "export": ("导出",),
    "model": ("建模",),
}


def _expand(tokens: set[str], raw: str) -> set[str]:
    """按同义桥扩展查询词元（含多字词整词命中，如「智能家居」「原理图」）。"""
    out = set(tokens)
    low = raw.lower()
    for key, vals in _SYNONYMS.items():
        if key in tokens or (len(key) > 1 and key in low):
            out.update(vals)
    return out


class ProfileRegistry:
    def __init__(self) -> None:
        self._profiles: dict[str, AppProfile] = {}
        self._adapter_factories: dict[str, Callable[[AppProfile], AppAdapter]] = {}

    def register(self, profile: AppProfile, adapter_factory: Callable[[AppProfile], AppAdapter]) -> None:
        errs = profile.validate()
        if errs:
            raise ValueError("；".join(errs))
        self._profiles[profile.app_id] = profile
        self._adapter_factories[profile.app_id] = adapter_factory

    def app_ids(self) -> list[str]:
        return sorted(self._profiles)

    def get(self, app_id: str) -> Optional[AppProfile]:
        return self._profiles.get(app_id)

    def make_adapter(self, app_id: str) -> Optional[AppAdapter]:
        prof = self._profiles.get(app_id)
        fac = self._adapter_factories.get(app_id)
        if prof is None or fac is None:
            return None
        return fac(prof)

    def describe_app(self, app_id: str) -> Optional[dict]:
        prof = self._profiles.get(app_id)
        if prof is None:
            return None
        return {
            "app_id": prof.app_id,
            "display_name": prof.display_name,
            "level": int(prof.level),
            "source_repo": prof.source_repo,
            "verbs": [
                {"name": v.name, "summary": v.summary, "params": v.params, "aliases": list(v.aliases)}
                for v in prof.verbs
            ],
            "prompt_snippet": prof.prompt_snippet,
        }

    def search_verbs(self, query: str, limit: int = 10) -> list[dict]:
        """跨所有软件的动词语义检索（词元 Jaccard + 中英同义桥 + 动词名/别名直命中加权）。"""
        q = _tokens(query)
        qx = _expand(q, query)
        results: list[tuple[float, dict]] = []
        for prof in self._profiles.values():
            for v in prof.verbs:
                text = v.search_text() + " " + prof.display_name + " " + prof.app_id
                toks = _tokens(text)
                if not toks:
                    continue
                inter = len(q & toks)
                xinter = len((qx - q) & toks)
                jacc = inter / len(q | toks) if (q | toks) else 0.0
                sub = 0.3 if query.lower() in text.lower() else 0.0
                names = {v.name.lower(), *(a.lower() for a in v.aliases)}
                direct = 0.35 if names & qx else 0.0
                score = jacc + sub + 0.1 * inter + 0.08 * xinter + direct
                if score > 0:
                    results.append((score, {
                        "app_id": prof.app_id,
                        "verb": v.name,
                        "summary": v.summary,
                        "score": round(score, 3),
                    }))
        results.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in results[:limit]]
