"""DAO AI dock panel — the human/AI conversation surface, living inside FreeCAD.

A dockable Qt widget added to FreeCAD's own main window so it persists across
every workbench. The human types intent (or clicks a quick chip); the engine
turns it into real operations on the live document, which appear instantly in
FreeCAD's native 3D view and tree. The human keeps full manual control at all
times — this panel only ever *adds* to the same shared document and undo stack.
"""
import json
import threading

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

import dao_agent
import dao_api
import dao_llm
import dao_prompts
import dao_sessions
from dao_engine import DAOEngine

DOCK_NAME = "DAO_AI_Panel"

_QUICK = [
    "box 40x30x10 name plate",
    "cylinder r=6 h=40 name hole",
    "cut hole from plate",
    "fillet plate radius 2",
    "polar pattern lug count 6",
    "measure plate",
    "perceive",
    "assembly demo",
    "solve press_fit",
    "solve safe_fillet",
    "solve bolt_circle",
    "solve bearing_block",
    "solve l_bracket",
    "solve pin_joint",
    "solve gear_pair",
    "solve hinge",
    "list objects",
    "reset",
]

# A self-contained multi-part assembly, driven entirely by direct tool calls —
# proof the agent can compose complex builds (parts + container + links + BOM).
_ASM_DEMO = json.dumps([
    {"tool": "solid.box", "args": {"name": "base", "length": 80, "width": 80, "height": 8}},
    {"tool": "solid.cylinder", "args": {"name": "post", "radius": 6, "height": 50}},
    {"tool": "solid.cylinder", "args": {"name": "cap", "radius": 12, "height": 6}},
    {"tool": "asm.create", "args": {"name": "Rig"}},
    {"tool": "asm.add", "args": {"name": "plate", "body": "base", "fixed": True}},
    {"tool": "asm.add", "args": {"name": "col", "body": "post", "placement": {"pos": [40, 40, 8]}}},
    {"tool": "asm.add", "args": {"name": "top", "body": "cap", "placement": {"pos": [40, 40, 58]}}},
    {"tool": "asm.bom", "args": {}},
])


class DAOPanel(QtWidgets.QWidget):
    # emitted (possibly from worker/HTTP threads) to run one tool call on the
    # main GUI thread; the payload dict carries a threading.Event to sync on.
    actRequested = QtCore.Signal(object)

    def __init__(self, parent=None):
        super(DAOPanel, self).__init__(parent)
        self.engine = DAOEngine()
        self.conv = dao_sessions.create("FreeCAD \u4f1a\u8bdd")
        self._worker = None
        self._api = None
        self._build_ui()
        self.actRequested.connect(self._on_act_request,
                                  QtCore.Qt.QueuedConnection)
        self._say("dao", "道法自然。我已接入当前 FreeCAD 文档。"
                          "用中文/英文描述你的意图，或点下方快捷指令；"
                          "你手动建的对象我也能引用，AI 的每步都可 Ctrl+Z 撤销。")
        self._maybe_start_api()

    # -- ui ----------------------------------------------------------------- #
    def _build_ui(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setStyleSheet(
            "QTabWidget::pane{border:0;}"
            "QTabBar::tab{background:#141a22;color:#8b98a9;padding:5px 14px;"
            "border:none;font-size:12px;}"
            "QTabBar::tab:selected{background:#0d1117;color:#e6edf3;"
            "border-bottom:2px solid #2563eb;}")
        outer.addWidget(self.tabs)

        chat = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(chat)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        # -- AI IDE top bar: conversation switcher + settings ------------- #
        top = QtWidgets.QHBoxLayout()
        self.conv_box = QtWidgets.QComboBox()
        self.conv_box.setStyleSheet(
            "QComboBox{background:#0d1117;color:#e6edf3;border:1px solid "
            "#2f3d4f;border-radius:6px;padding:3px 6px;}")
        self._reload_convs()
        self.conv_box.currentIndexChanged.connect(self._switch_conv)
        newc = QtWidgets.QPushButton("\uff0b")
        newc.setFixedWidth(28)
        newc.setToolTip("\u65b0\u5efa\u4f1a\u8bdd")
        newc.clicked.connect(self._new_conv)
        gear = QtWidgets.QPushButton("\u2699")
        gear.setFixedWidth(28)
        gear.setToolTip("AI \u8bbe\u7f6e\uff1a\u6a21\u578b\u8def\u7531 / \u63d0\u793a\u8bcd\u7ba1\u7406")
        gear.clicked.connect(self._settings)
        for b in (newc, gear):
            b.setStyleSheet(
                "QPushButton{background:#1b2430;color:#cfe2ff;border:1px "
                "solid #2f3d4f;border-radius:6px;padding:3px;}"
                "QPushButton:hover{background:#243246;}")
        chips_btn = QtWidgets.QPushButton("\u26a1")
        chips_btn.setFixedWidth(28)
        chips_btn.setCheckable(True)
        chips_btn.setToolTip("\u5feb\u6377\u6307\u4ee4")
        chips_btn.setStyleSheet(
            "QPushButton{background:#1b2430;color:#cfe2ff;border:1px "
            "solid #2f3d4f;border-radius:6px;padding:3px;}"
            "QPushButton:hover{background:#243246;}"
            "QPushButton:checked{background:#2563eb;color:white;}")
        top.addWidget(self.conv_box, 1)
        top.addWidget(chips_btn)
        top.addWidget(newc)
        top.addWidget(gear)
        lay.addLayout(top)

        self.log = QtWidgets.QTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet(
            "QTextEdit{background:#10141b;color:#d7dde6;border:1px solid #2a3340;"
            "font-family:Consolas,monospace;font-size:12px;}")
        lay.addWidget(self.log, 1)

        # Quick chips live behind the \u26a1 toggle so the conversation owns
        # the panel by default, like any AI IDE.
        self.chips_panel = QtWidgets.QWidget()
        chips = QtWidgets.QGridLayout(self.chips_panel)
        chips.setContentsMargins(0, 0, 0, 0)
        chips.setSpacing(4)
        for i, c in enumerate(_QUICK):
            b = QtWidgets.QPushButton(c)
            b.setCursor(QtCore.Qt.PointingHandCursor)
            b.setStyleSheet(
                "QPushButton{background:#1b2430;color:#cfe2ff;border:1px solid #2f3d4f;"
                "border-radius:10px;padding:3px 8px;font-size:11px;}"
                "QPushButton:hover{background:#243246;}")
            b.clicked.connect(lambda _=False, t=c: self._run(t))
            chips.addWidget(b, i // 2, i % 2)
        self.chips_panel.hide()
        chips_btn.toggled.connect(self.chips_panel.setVisible)
        lay.addWidget(self.chips_panel)

        # -- AI IDE status bar: model badge + activity + stop ------------- #
        status = QtWidgets.QHBoxLayout()
        self.status_lbl = QtWidgets.QLabel()
        self.status_lbl.setStyleSheet("QLabel{color:#8b98a9;font-size:11px;}")
        self.stop_btn = QtWidgets.QPushButton("\u25a0 \u505c\u6b62")
        self.stop_btn.setStyleSheet(
            "QPushButton{background:#7f1d1d;color:#fecaca;border:none;"
            "border-radius:6px;padding:2px 10px;font-size:11px;}"
            "QPushButton:hover{background:#991b1b;}")
        self.stop_btn.clicked.connect(self._stop_llm)
        self.stop_btn.hide()
        status.addWidget(self.status_lbl, 1)
        status.addWidget(self.stop_btn)
        lay.addLayout(status)
        self._set_status(idle=True)

        row = QtWidgets.QHBoxLayout()
        self.input = _ChatInput()
        self.input.setPlaceholderText(
            "\u63cf\u8ff0\u4f60\u7684\u610f\u56fe\uff0cEnter \u53d1\u9001\uff0c"
            "Shift+Enter \u6362\u884c\uff1b\u9009\u4e2d 3D \u5bf9\u8c61\u540e"
            "\u53ef\u76f4\u63a5\u8bf4\u201c\u628a\u5b83\u2026\u201d")
        self.input.setStyleSheet(
            "QPlainTextEdit{background:#0d1117;color:#e6edf3;border:1px solid "
            "#2f3d4f;border-radius:6px;padding:6px;}")
        self.input.submitted.connect(self._send)
        send = QtWidgets.QPushButton("发送")
        send.setStyleSheet(
            "QPushButton{background:#2563eb;color:white;border:none;border-radius:6px;"
            "padding:6px 14px;font-weight:bold;}QPushButton:hover{background:#1d4ed8;}")
        send.clicked.connect(self._send)
        row.addWidget(self.input, 1)
        row.addWidget(send)
        lay.addLayout(row)

        self.tabs.addTab(chat, "\u5bf9\u8bdd")
        self.tabs.addTab(self._build_data_tab(), "\u6570\u636e")
        self.tabs.addTab(self._build_mgmt_tab(), "\u7ba1\u7406")
        self.tabs.currentChanged.connect(self._on_tab_changed)

    # -- data tab: the live-project truth, always current ----------------- #
    def _build_data_tab(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(6)
        bar = QtWidgets.QHBoxLayout()
        self.data_auto = QtWidgets.QCheckBox("\u5b9e\u65f6\u5237\u65b0")
        self.data_auto.setChecked(True)
        self.data_auto.setStyleSheet("QCheckBox{color:#8b98a9;font-size:11px;}")
        refresh = QtWidgets.QPushButton("\u5237\u65b0")
        refresh.setStyleSheet(
            "QPushButton{background:#1b2430;color:#cfe2ff;border:1px solid "
            "#2f3d4f;border-radius:6px;padding:3px 10px;font-size:11px;}"
            "QPushButton:hover{background:#243246;}")
        refresh.clicked.connect(self._refresh_data)
        self.data_stamp = QtWidgets.QLabel("")
        self.data_stamp.setStyleSheet("QLabel{color:#607086;font-size:10px;}")
        bar.addWidget(self.data_auto)
        bar.addWidget(self.data_stamp, 1)
        bar.addWidget(refresh)
        v.addLayout(bar)
        self.data_view = QtWidgets.QPlainTextEdit()
        self.data_view.setReadOnly(True)
        self.data_view.setStyleSheet(
            "QPlainTextEdit{background:#10141b;color:#d7dde6;border:1px solid "
            "#2a3340;font-family:Consolas,monospace;font-size:11px;}")
        v.addWidget(self.data_view, 1)
        self._data_timer = QtCore.QTimer(self)
        self._data_timer.setInterval(2000)
        self._data_timer.timeout.connect(self._auto_refresh_data)
        return w

    def _on_tab_changed(self, idx):
        if self.tabs.widget(idx) is self.data_view.parentWidget():
            self._refresh_data()
            self._data_timer.start()
        else:
            self._data_timer.stop()
        if self.tabs.tabText(idx) == "\u7ba1\u7406":
            self._refresh_mgmt()

    def _auto_refresh_data(self):
        if self.data_auto.isChecked() and self.data_view.isVisible():
            self._refresh_data()

    def _refresh_data(self):
        try:
            self.engine._ensure_doc()
            fn = self.engine.handlers.get("project.brief")
            if fn is None:
                self.data_view.setPlainText("project.* \u672a\u52a0\u8f7d")
                return
            out = fn({"relations": False})
            # keep the human's scroll position on live refresh
            sb = self.data_view.verticalScrollBar()
            pos = sb.value()
            self.data_view.setPlainText(out.get("markdown", ""))
            sb.setValue(min(pos, sb.maximum()))
            import time as _t
            self.data_stamp.setText(
                "%s \u00b7 %d \u5bf9\u8c61%s" % (
                    _t.strftime("%H:%M:%S"), out.get("object_count", 0),
                    "" if out.get("ok") else " \u00b7 \u26a0 \u6709\u95ee\u9898"))
        except Exception as exc:
            self.data_view.setPlainText("\u72b6\u6001\u83b7\u53d6\u5931\u8d25: %s" % exc)

    # -- management tab: engine / API / sessions at a glance --------------- #
    def _build_mgmt_tab(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(6)
        self.mgmt_view = QtWidgets.QPlainTextEdit()
        self.mgmt_view.setReadOnly(True)
        self.mgmt_view.setStyleSheet(
            "QPlainTextEdit{background:#10141b;color:#d7dde6;border:1px solid "
            "#2a3340;font-family:Consolas,monospace;font-size:11px;}")
        v.addWidget(self.mgmt_view, 1)
        bar = QtWidgets.QHBoxLayout()
        self.api_btn = QtWidgets.QPushButton("\u542f\u52a8 Agent API")
        self.api_btn.setStyleSheet(
            "QPushButton{background:#1b2430;color:#cfe2ff;border:1px solid "
            "#2f3d4f;border-radius:6px;padding:4px 10px;font-size:11px;}"
            "QPushButton:hover{background:#243246;}")
        self.api_btn.clicked.connect(self._toggle_api)
        cfgbtn = QtWidgets.QPushButton("AI \u8bbe\u7f6e\u2026")
        cfgbtn.setStyleSheet(self.api_btn.styleSheet())
        cfgbtn.clicked.connect(self._settings)
        bar.addWidget(self.api_btn)
        bar.addWidget(cfgbtn)
        bar.addStretch(1)
        v.addLayout(bar)
        return w

    def _toggle_api(self):
        cfg = dao_llm.load_config()
        cfg["api_enabled"] = not cfg.get("api_enabled")
        dao_llm.save_config(cfg)
        self._maybe_start_api()
        self._refresh_mgmt()

    def _refresh_mgmt(self):
        cfg = dao_llm.load_config()
        try:
            self.engine._ensure_doc()
            nops = len(self.engine.handlers)
        except Exception:
            nops = 0
        lines = ["== \u5f15\u64ce ==",
                 "\u5de5\u5177\u6570: %d" % nops,
                 "\u6587\u6863: %s" % (App.ActiveDocument.Name
                                       if App.ActiveDocument else "(\u65e0)"),
                 "",
                 "== \u6a21\u578b ==",
                 "model: %s" % cfg.get("model"),
                 "base_url: %s" % cfg.get("base_url"),
                 "\u5df2\u914d\u7f6e: %s" % ("\u662f" if dao_llm.configured()
                                             else "\u5426\uff08\u672c\u5730\u89c4\u5219\u56de\u9000\uff09"),
                 "",
                 "== Agent API =="]
        if self._api is not None:
            lines += ["\u72b6\u6001: \u8fd0\u884c\u4e2d http://127.0.0.1:%d"
                      % self._api.port,
                      "\u63a5\u5165\u6307\u5357: AGENT_ACCESS.md"]
            self.api_btn.setText("\u505c\u6b62 Agent API")
        else:
            lines += ["\u72b6\u6001: \u672a\u542f\u52a8"]
            self.api_btn.setText("\u542f\u52a8 Agent API")
        lines += ["", "== \u4f1a\u8bdd =="]
        for c in dao_sessions.list_all()[:12]:
            mark = " \u2190" if c["id"] == self.conv["id"] else ""
            lines.append("%s (%d)%s" % (c["title"], c["count"], mark))
        self.mgmt_view.setPlainText("\n".join(lines))

    # -- chat (AI-IDE bubbles) ---------------------------------------------- #
    def _set_status(self, idle=True, text=None):
        cfg = dao_llm.load_config()
        model = cfg["model"] if dao_llm.configured(cfg) else "\u672a\u914d\u7f6e\u6a21\u578b"
        api = " \u00b7 API:%s" % cfg.get("api_port", dao_api.DEFAULT_PORT) \
            if self._api is not None else ""
        state = text or ("\u5c31\u7eea" if idle else "\u601d\u8003\u4e2d\u2026")
        self.status_lbl.setText("\u25cf %s \u00b7 %s%s" % (model, state, api))

    def _say(self, who, text):
        """Render one chat bubble, AI-IDE style: user right/blue, DAO left/
        dark card, system + errors as thin captions."""
        if who == "you":
            html = ('<table width="100%%"><tr><td width="18%%"></td>'
                    '<td style="background:#1d4ed8;color:#eff6ff;'
                    'border-radius:10px;padding:6px 10px;">%s</td></tr>'
                    '</table>' % text)
        elif who == "dao":
            html = ('<table width="100%%"><tr>'
                    '<td style="background:#1b2430;color:#d1fae5;'
                    'border-radius:10px;padding:6px 10px;">'
                    '<span style="color:#34d399;"><b>DAO</b></span>'
                    '&nbsp; %s</td><td width="18%%"></td></tr>'
                    '</table>' % text)
        elif who == "err":
            html = ('<div style="color:#fca5a5;padding:2px 4px;">'
                    '\u26a0 %s</div>' % text)
        else:
            html = ('<div style="color:#8b98a9;font-size:11px;'
                    'padding:1px 4px;">%s</div>' % text)
        self.log.append(html)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _tool_card(self, rec):
        """Collaped tool-call card: one line per call, monospace, \u2713/\u2717."""
        args = _fmt_args(rec.get("args") or {})
        if rec.get("ok"):
            body = ('<span style="color:#34d399;">\u2713</span> '
                    '<b>%s</b><span style="color:#607086;">%s</span> '
                    '<span style="color:#8b98a9;">%s</span>'
                    % (rec["tool"], args, _fmt(rec.get("data", {}))))
        else:
            body = ('<span style="color:#f87171;">\u2717</span> '
                    '<b>%s</b><span style="color:#607086;">%s</span> '
                    '<span style="color:#fca5a5;">%s</span>'
                    % (rec["tool"], args, rec.get("error")))
        self.log.append(
            '<div style="background:#0d1117;border:1px solid #2a3340;'
            'border-radius:6px;padding:3px 8px;font-family:Consolas,monospace;'
            'font-size:11px;color:#d7dde6;">%s</div>' % body)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _send(self):
        text = self.input.toPlainText().strip()
        if text:
            self.input.clear()
            self._run(text)

    # -- AI IDE: conversations / settings ------------------------------- #
    def _reload_convs(self):
        self.conv_box.blockSignals(True)
        self.conv_box.clear()
        self._conv_ids = []
        for c in dao_sessions.list_all():
            self.conv_box.addItem("%s (%d)" % (c["title"], c["count"]))
            self._conv_ids.append(c["id"])
        if getattr(self, "conv", None) and self.conv["id"] in self._conv_ids:
            self.conv_box.setCurrentIndex(self._conv_ids.index(self.conv["id"]))
        self.conv_box.blockSignals(False)

    def _switch_conv(self, idx):
        if 0 <= idx < len(self._conv_ids):
            loaded = dao_sessions.load(self._conv_ids[idx])
            if loaded:
                self.conv = loaded
                self.log.clear()
                for m in loaded.get("messages", []):
                    if m["role"] == "user" and \
                            not m["content"].startswith("TOOL_RESULTS:"):
                        self._say("you", m["content"])
                    elif m["role"] == "assistant":
                        env = dao_llm.parse_envelope(m["content"])
                        if env["say"]:
                            self._say("dao", env["say"])

    def _new_conv(self):
        self.conv = dao_sessions.create("FreeCAD \u4f1a\u8bdd")
        self.log.clear()
        self._reload_convs()

    def _settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec_():
            self._say("sys", "AI \u8bbe\u7f6e\u5df2\u4fdd\u5b58\uff1a%s @ %s"
                      % (dao_llm.load_config()["model"],
                         dao_llm.load_config()["base_url"]))
            self._maybe_start_api()
            self._set_status(idle=True)

    # -- reverse-access API (cloud agents plug in; see AGENT_ACCESS.md) ---- #
    def _maybe_start_api(self):
        cfg = dao_llm.load_config()
        if self._api is not None:
            self._api.stop()
            self._api = None
        if not cfg.get("api_enabled"):
            return
        try:
            self.engine._ensure_doc()
            self._api = dao_api.DaoAPI(
                self._threadsafe_actor, sorted(self.engine.handlers),
                port=int(cfg.get("api_port", dao_api.DEFAULT_PORT))).start()
            self._say("sys", "Agent API \u5df2\u542f\u52a8\uff1a"
                      "http://127.0.0.1:%d\uff08\u89c1 AGENT_ACCESS.md\uff09"
                      % self._api.port)
        except Exception as exc:
            self._say("err", "Agent API \u542f\u52a8\u5931\u8d25: %s" % exc)

    def _threadsafe_actor(self, tool, args):
        """Run one tool call on the GUI thread, callable from any thread."""
        if QtCore.QThread.currentThread() is self.thread():
            return self._llm_actor(tool, args)
        req = {"tool": tool, "args": args,
               "event": threading.Event(), "result": None, "error": None}
        self.actRequested.emit(req)
        if not req["event"].wait(timeout=300):
            raise TimeoutError("GUI thread did not answer within 300s")
        if req["error"] is not None:
            raise req["error"]
        return req["result"]

    @QtCore.Slot(object)
    def _on_act_request(self, req):
        try:
            req["result"] = self._llm_actor(req["tool"], req["args"])
        except Exception as exc:
            req["error"] = exc
        finally:
            req["event"].set()
        rec = ({"tool": req["tool"], "args": req["args"], "ok": True,
                "data": req["result"]}
               if req["error"] is None else
               {"tool": req["tool"], "args": req["args"], "ok": False,
                "error": str(req["error"])})
        self._tool_card(rec)
        self._refresh_view()

    def _llm_actor(self, tool, args):
        """Execute one LLM tool call on the live document (own undo step)."""
        doc = self.engine._ensure_doc()
        fn = self.engine.handlers.get(tool)
        if fn is None:
            raise KeyError("unknown op: %s" % tool)
        doc.openTransaction("DAO AI: %s" % tool)
        try:
            data = fn(args)
        finally:
            doc.commitTransaction()
            doc.recompute()
        return data if isinstance(data, dict) else {"value": data}

    def _run_llm(self, text):
        """AI IDE turn: the model thinks in a worker thread (UI stays live);
        every tool call is marshaled back to the GUI thread and rendered as a
        card the moment it runs; \u25a0 \u505c\u6b62 cancels at the next step."""
        if self._worker is not None and self._worker.isRunning():
            self._say("err", "\u4e0a\u4e00\u8f6e\u8fd8\u5728\u8fdb\u884c\uff0c"
                             "\u5148 \u25a0 \u505c\u6b62\u6216\u7a0d\u5019")
            return
        cfg = dao_llm.load_config()
        doc = self.engine._ensure_doc()
        self._objs_before = len(doc.Objects)
        sel = _selection_context()
        if sel:
            self._say("sys", "\u5df2\u9644\u5e26\u5f53\u524d\u9009\u4e2d\uff1a%s" % sel)
            text = "[\u7528\u6237\u5f53\u524d\u5728 3D \u89c6\u56fe\u9009\u4e2d\uff1a%s]\n%s" % (sel, text)
        prompt = dao_prompts.system_prompt(
            cfg.get("system_prompt_id", "default"),
            sorted(self.engine.handlers))
        prompt += ("\nAlways answer `say` in the same language the user "
                   "writes in (\u4e2d\u6587\u7528\u6237\u7528\u4e2d\u6587\u56de\u7b54).")
        worker = _LLMWorker(
            self._threadsafe_actor, cfg, prompt,
            text, list(self.conv.get("messages", [])))
        worker.said.connect(lambda t: self._say("dao", t))
        worker.failed.connect(self._on_turn_failed)
        worker.finished_turn.connect(self._on_turn_done)
        self._worker = worker
        self.stop_btn.show()
        self._set_status(idle=False)
        worker.start()

    def _stop_llm(self):
        if self._worker is not None:
            self._worker.cancel()
            self._set_status(idle=False, text="\u6b63\u5728\u505c\u6b62\u2026")

    @QtCore.Slot(str)
    def _on_turn_failed(self, msg):
        self._say("err", "LLM: %s" % msg)
        App.Console.PrintWarning("DAO LLM: %s\n" % msg)
        self.stop_btn.hide()
        self._set_status(idle=True)

    @QtCore.Slot(object)
    def _on_turn_done(self, out):
        self.conv["messages"] = out["messages"]
        dao_sessions.save_messages(self.conv["id"], out["messages"])
        self._reload_convs()
        verify = out.get("verify")
        if verify is not None:
            diff = verify.get("diff") or {}
            delta = ""
            if diff and (diff.get("added") or diff.get("removed")
                         or diff.get("changed")):
                bits = []
                if diff.get("added"):
                    bits.append("+%d" % len(diff["added"]))
                if diff.get("removed"):
                    bits.append("-%d" % len(diff["removed"]))
                if diff.get("changed"):
                    bits.append("~%d" % len(diff["changed"]))
                delta = "，本轮变更 " + "/".join(bits)
            if verify.get("ok"):
                self._say("sys", "回读校验 ✓ 模型健康（project.state OK%s）" % delta)
            elif verify.get("ok") is False:
                self._say("sys", "回读校验 ✗ 遗留 %d 个问题：%s" % (
                    len(verify["issues"]),
                    "; ".join("%s(%s)" % (i.get("kind"), i.get("object"))
                              for i in verify["issues"][:4])))
        doc = App.ActiveDocument
        grew = doc is not None and \
            len(doc.Objects) > getattr(self, "_objs_before", 0)
        self._refresh_view(fit=grew)
        self.stop_btn.hide()
        self._set_status(idle=True)

    def _run(self, text):
        self._say("you", text)
        low = text.strip().lower()
        if low in ("ops", "tools", "能力", "工具"):
            self._say("dao", "%d tools: %s" % (len(self.engine.ops()),
                                               ", ".join(self.engine.ops())))
            return
        if low.startswith(("solve ", "目标 ", "自主 ")):
            self._solve(low.split(None, 1)[1].strip())
            return
        intent = dao_agent.resolve_goal_intent(text)
        if intent is not None:
            name, overrides = intent
            if overrides:
                self._say("dao", "识别到目标意图：%s，参数 %s" % (name, _fmt_params(overrides)))
            else:
                self._say("dao", "识别到目标意图：%s" % name)
            self._solve(name, **overrides)
            return
        if low in ("assembly demo", "装配演示", "asm demo"):
            text = _ASM_DEMO
        elif dao_llm.configured() and not text.lstrip().startswith(("[", "{")):
            # AI IDE mode: a configured model drives the conversation; the
            # local planner remains the offline fallback and JSON passthrough.
            self._run_llm(text)
            return
        had_objects = bool(App.ActiveDocument and App.ActiveDocument.Objects)
        try:
            note, results = self.engine.run(text)
        except Exception as exc:
            self._say("err", "engine: %s" % exc)
            return
        if not results:
            self._say("err", note)
            return
        if note:
            self._say("dao", note)
        for r in results:
            if not r.get("ok"):
                self._say("err", "%s ✗ %s" % (r["tool"], r.get("error")))
                continue
            data = r.get("data", {})
            self._say("sys", "%s → %s" % (r["tool"], _fmt(data)))
            self._maybe_show_perception(r["tool"], data)
        self._refresh_view(fit=not had_objects)

    def _solve(self, goal, **overrides):
        """Run the autonomous closed loop on a goal, narrating each iteration so the
        human watches the model self-correct in the live 3D view."""
        self._say("dao", "自主闭环求解目标 <b>%s</b>：建模 → 感知 → 验证 → 自纠 → 循环" % goal)
        first = {"v": True}

        def on_iter(step):
            verdict = "✓ 通过" if step["passed"] else ("✗ " + ", ".join(step["failed"]))
            self._say("sys", "iter %d  %s  → %s"
                      % (step["iter"], _fmt_params(step["params"]), verdict))
            for c in step["checks"]:
                if not c["ok"]:
                    self._say("sys", "&nbsp;&nbsp;· %s: %s" % (c["name"], _fmt_check(c)))
            self._refresh_view(fit=first["v"])
            first["v"] = False

        try:
            res = self.engine.solve(goal, on_iteration=on_iter, **overrides)
        except Exception as exc:
            self._say("err", "solve: %s" % exc)
            return
        if res.get("error"):
            self._say("err", "%s（可用：%s）" % (res["error"], ", ".join(res.get("available", []))))
            return
        tag = "达成" if res["solved"] else "未达成（预算用尽）"
        self._say("dao", "目标 <b>%s</b> %s，共 %d 次迭代；最终参数 %s"
                  % (goal, tag, res["iterations"], _fmt_params(res["final_params"])))
        try:
            per = self.engine.perceive({})
            self._maybe_show_perception("gui.perceive", per)
        except Exception:
            pass

    def _maybe_show_perception(self, tool, data):
        """Render scene summary + embed the captured viewport image in the log."""
        scene = data.get("scene") if isinstance(data, dict) else None
        if scene:
            self._say("dao", _scene_summary(scene))
            sel = data.get("selection") or {}
            if sel.get("count"):
                self._say("dao", "human selection: %s" % _fmt_selection(sel))
        snap = data.get("snapshot") if isinstance(data, dict) else None
        path = (snap or {}).get("path") if isinstance(snap, dict) else None
        if not path and tool == "gui.snapshot":
            path = data.get("path")
        if path:
            url = QtCore.QUrl.fromLocalFile(path).toString()
            self.log.append(
                '<img src="%s" width="320" '
                'style="border:1px solid #2a3340;margin:4px 0;">' % url)
            self.log.verticalScrollBar().setValue(
                self.log.verticalScrollBar().maximum())

    def _refresh_view(self, fit=False):
        doc = App.ActiveDocument
        if doc:
            doc.recompute()
        Gui.updateGui()
        # Only fit on the first object so we never hijack the human's camera.
        if fit:
            try:
                Gui.SendMsgToActiveView("ViewFit")
            except Exception:
                pass


class _ChatInput(QtWidgets.QPlainTextEdit):
    """AI-IDE composer: Enter sends, Shift+Enter inserts a newline, and the
    box grows with content up to four lines."""

    submitted = QtCore.Signal()

    def __init__(self, parent=None):
        super(_ChatInput, self).__init__(parent)
        self.setTabChangesFocus(True)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.textChanged.connect(self._autosize)
        self._autosize()

    def _autosize(self):
        fm = self.fontMetrics()
        lines = min(max(self.document().blockCount(), 1), 4)
        pad = 2 * int(self.document().documentMargin()) + \
            2 * self.frameWidth() + 12  # 12 = stylesheet padding (6 top+bottom)
        self.setFixedHeight(fm.lineSpacing() * lines + pad)

    def keyPressEvent(self, ev):
        if ev.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter) and \
                not ev.modifiers() & QtCore.Qt.ShiftModifier:
            self.submitted.emit()
            return
        super(_ChatInput, self).keyPressEvent(ev)


def _selection_context():
    """The human's live 3D selection, phrased for the model (labels + sub-
    elements), so \u201c\u628a\u5b83\u5012\u89d2\u201d resolves naturally."""
    try:
        sel = Gui.Selection.getSelectionEx()
    except Exception:
        return ""
    parts = []
    for s in sel[:6]:
        subs = ",".join(s.SubElementNames) if s.SubElementNames else ""
        parts.append(s.Object.Name + (("(%s)" % subs) if subs else ""))
    return "; ".join(parts)


def _fmt_args(args):
    if not isinstance(args, dict) or not args:
        return ""
    bits = ["%s=%s" % (k, v) for k, v in list(args.items())[:4]
            if not isinstance(v, (dict, list))]
    return "(%s)" % ", ".join(bits) if bits else ""


_PARAM_KEYS = ("pin_r", "shaft_r", "bore_r", "hole_r", "radius", "bcr", "n")


def _fmt_params(p):
    if not isinstance(p, dict):
        return str(p)
    bits = ["%s=%s" % (k, p[k]) for k in _PARAM_KEYS if k in p]
    return ", ".join(dict.fromkeys(bits)) or ", ".join(
        "%s=%s" % (k, v) for k, v in list(p.items())[:3])


def _fmt_check(c):
    out = c.get("name", "")
    if "measured" in c:
        out = "measured=%s" % (c["measured"],)
    if "target" in c:
        out += " target=%s" % (c["target"],)
    if "detail" in c and c["detail"]:
        out += " %s" % (c["detail"],)
    return out


def _fmt(data):
    if not isinstance(data, dict):
        return str(data)
    keep = ("volume", "area", "faces", "edges", "value", "document", "count",
            "objects", "interfering", "mass", "assembly", "component", "linked",
            "solved", "grounded", "line_items", "component_count", "path",
            "problems", "placement", "view")
    bits = []
    for k in keep:
        if k in data:
            v = data[k]
            if isinstance(v, (list, dict)):
                v = "[%d]" % len(v)
            bits.append("%s=%s" % (k, v))
    return ", ".join(bits) if bits else "ok"


def _scene_summary(scene):
    n = scene.get("count", 0)
    bb = scene.get("bbox")
    span = ("span=%s" % bb["dims"]) if bb else ""
    errs = scene.get("errors") or []
    head = "scene: %d object(s) %s" % (n, span)
    if errs:
        head += " · errors: %s" % ", ".join(errs)
    parts = []
    for o in scene.get("objects", [])[:6]:
        d = o.get("bbox", {}).get("dims") if o.get("bbox") else None
        vol = o.get("volume")
        tag = o.get("label") or o.get("name")
        seg = tag
        if d:
            seg += " %gx%gx%g" % tuple(d)
        if vol is not None:
            seg += " V=%g" % vol
        if o.get("visible") is False:
            seg += " (hidden)"
        parts.append(seg)
    if parts:
        head += "<br>&nbsp;&nbsp;" + "<br>&nbsp;&nbsp;".join(parts)
    return head


def _fmt_selection(sel):
    out = []
    for s in sel.get("selected", []):
        sub = ("/" + ",".join(s["subs"])) if s.get("subs") else ""
        out.append("%s%s" % (s.get("label") or s.get("object"), sub))
    return "; ".join(out)


class _LLMWorker(QtCore.QThread):
    """Runs one conversational turn off the GUI thread. Tool calls hop back
    to the main thread through the panel's thread-safe actor; the network
    round-trips happen out here so FreeCAD never freezes mid-thought."""

    said = QtCore.Signal(str)
    failed = QtCore.Signal(str)
    finished_turn = QtCore.Signal(object)

    def __init__(self, actor, cfg, system_prompt, text, history):
        super(_LLMWorker, self).__init__()
        self._actor = actor
        self._cfg = cfg
        self._system_prompt = system_prompt
        self._text = text
        self._history = history
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        def transport(cfg, messages):
            if self._cancel.is_set():
                raise RuntimeError("\u5df2\u7531\u7528\u6237\u505c\u6b62")
            return dao_llm.http_transport(cfg, messages)

        def actor(tool, args):
            if self._cancel.is_set():
                raise RuntimeError("\u5df2\u7531\u7528\u6237\u505c\u6b62")
            return self._actor(tool, args)

        agent = dao_llm.LLMAgent(actor, cfg=self._cfg,
                                 system_prompt=self._system_prompt,
                                 transport=transport)

        def on_event(kind, payload):
            if kind == "say":
                self.said.emit(payload)

        try:
            out = agent.ask(self._text, history=self._history,
                            on_event=on_event)
        except Exception as exc:
            self.failed.emit("%s: %s" % (type(exc).__name__, exc))
            return
        self.finished_turn.emit(out)


class SettingsDialog(QtWidgets.QDialog):
    """AI IDE settings — provider/model routing plus prompt management, the
    same knobs a Devin-Desktop-style IDE exposes, persisted as plain JSON."""

    def __init__(self, parent=None):
        super(SettingsDialog, self).__init__(parent)
        self.setWindowTitle("DAO AI 设置")
        self.setMinimumWidth(460)
        cfg = dao_llm.load_config()
        form = QtWidgets.QFormLayout(self)

        self.base_url = QtWidgets.QLineEdit(cfg["base_url"])
        self.api_key = QtWidgets.QLineEdit(cfg["api_key"])
        self.api_key.setEchoMode(QtWidgets.QLineEdit.Password)
        self.model = QtWidgets.QLineEdit(cfg["model"])
        form.addRow("Base URL（任意 OpenAI 兼容端点）", self.base_url)
        form.addRow("API Key", self.api_key)
        form.addRow("模型", self.model)

        self.prompt_box = QtWidgets.QComboBox()
        self._prompt_ids = []
        current = cfg.get("system_prompt_id", "default")
        for pid, p in sorted(dao_prompts.load_all().items()):
            self.prompt_box.addItem("%s (%s)" % (p["name"], pid))
            self._prompt_ids.append(pid)
        if current in self._prompt_ids:
            self.prompt_box.setCurrentIndex(self._prompt_ids.index(current))
        form.addRow("系统提示词", self.prompt_box)

        self.prompt_body = QtWidgets.QPlainTextEdit()
        self.prompt_body.setPlaceholderText(
            "编辑后以新 id 保存为自定义提示词（留空则使用所选提示词原文）")
        self.prompt_body.setFixedHeight(110)
        form.addRow("自定义提示词内容", self.prompt_body)
        self.prompt_id = QtWidgets.QLineEdit()
        self.prompt_id.setPlaceholderText("自定义提示词 id，如 my_style")
        form.addRow("保存为 id", self.prompt_id)

        self.api_enabled = QtWidgets.QCheckBox(
            "\u542f\u7528 Agent API\uff08\u4f9b\u4e91\u7aef Agent \u53cd\u5411"
            "\u63a5\u5165\uff0c\u89c1 AGENT_ACCESS.md\uff09")
        self.api_enabled.setChecked(bool(cfg.get("api_enabled")))
        form.addRow(self.api_enabled)
        self.api_port = QtWidgets.QLineEdit(
            str(cfg.get("api_port", dao_api.DEFAULT_PORT)))
        form.addRow("API \u7aef\u53e3", self.api_port)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def _save(self):
        pid = self._prompt_ids[self.prompt_box.currentIndex()] \
            if self._prompt_ids else "default"
        body = self.prompt_body.toPlainText().strip()
        new_id = self.prompt_id.text().strip()
        if body and new_id:
            dao_prompts.save(new_id, new_id, body)
            pid = new_id
        cfg = dao_llm.load_config()
        cfg.update({
            "base_url": self.base_url.text().strip(),
            "api_key": self.api_key.text().strip(),
            "model": self.model.text().strip(),
            "system_prompt_id": pid,
            "api_enabled": self.api_enabled.isChecked(),
        })
        try:
            cfg["api_port"] = int(self.api_port.text().strip())
        except ValueError:
            pass
        dao_llm.save_config(cfg)
        self.accept()


def ensure_panel():
    """Create the dock once and show it; re-show if already created."""
    mw = Gui.getMainWindow()
    if mw is None:
        return None
    existing = mw.findChild(QtWidgets.QDockWidget, DOCK_NAME)
    if existing is not None:
        existing.show()
        existing.raise_()
        return existing
    dock = QtWidgets.QDockWidget("DAO · AI 工作台", mw)
    dock.setObjectName(DOCK_NAME)
    dock.setWidget(DAOPanel(dock))
    dock.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea)
    mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
    dock.show()
    dock.raise_()
    return dock
