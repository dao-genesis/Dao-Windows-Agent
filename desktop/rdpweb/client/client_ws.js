/* WS 版 mstsc 客户端(多分身面板·官方RDP协议→canvas)。改 socket.io 为原生 WebSocket,
 * infos 只带 target(凭据由网关服务端持有,不下发浏览器);键盘路由到当前聚焦分身。 */
(function () {
  function mouseButtonMap(b) { if (b === 0) return 1; if (b === 2) return 2; return 0; }
  var focused = null; // 当前接管键鼠的分身 client

  function Client(canvas) {
    this.canvas = canvas;
    this.render = Mstsc.Canvas.create(canvas);
    this.ws = null;
    this.activeSession = false;
    this.install();
  }
  Client.prototype = {
    install: function () {
      var self = this;
      function off(e) { var o = Mstsc.elementOffset(self.canvas);
        // canvas 逻辑分辨率→显示尺寸的缩放换算
        var sx = self.canvas.width / self.canvas.clientWidth, sy = self.canvas.height / self.canvas.clientHeight;
        return { x: Math.round((e.clientX - o.left) * sx), y: Math.round((e.clientY - o.top) * sy) }; }
      this.canvas.addEventListener('mousemove', function (e) { if (!self.ws) return; var p = off(e); self.emit({ t: 'mouse', x: p.x, y: p.y, button: 0, isPressed: false }); });
      this.canvas.addEventListener('mousedown', function (e) { if (!self.ws) return; focused = self; markFocus(); var p = off(e); self.emit({ t: 'mouse', x: p.x, y: p.y, button: mouseButtonMap(e.button), isPressed: true }); e.preventDefault(); });
      this.canvas.addEventListener('mouseup', function (e) { if (!self.ws) return; var p = off(e); self.emit({ t: 'mouse', x: p.x, y: p.y, button: mouseButtonMap(e.button), isPressed: false }); e.preventDefault(); });
      this.canvas.addEventListener('contextmenu', function (e) { e.preventDefault(); });
      this.canvas.addEventListener('wheel', function (e) { if (!self.ws) return; var p = off(e);
        var isH = Math.abs(e.deltaX) > Math.abs(e.deltaY); var d = isH ? e.deltaX : e.deltaY;
        var step = Math.round(Math.abs(d) * 15 / 8); self.emit({ t: 'wheel', x: p.x, y: p.y, step: step, isNegative: d > 0, isHorizontal: isH }); e.preventDefault(); }, { passive: false });
      return this;
    },
    emit: function (o) { try { if (this.ws && this.ws.readyState === 1) this.ws.send(JSON.stringify(o)); } catch (e) {} },
    connect: function (target, next) {
      var self = this;
      var proto = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
      var ws = new WebSocket(proto + window.location.host + '/ws');
      this.ws = ws;
      ws.onopen = function () { self.emit({ t: 'infos', target: target, screen: { width: self.canvas.width, height: self.canvas.height }, locale: (navigator.language || 'en') }); };
      ws.onmessage = function (ev) { var m = JSON.parse(ev.data);
        if (m.t === 'connect') { self.activeSession = true; setStatus(self, '● 官方RDP已连', '#7fdc7f'); }
        else if (m.t === 'bitmap') { m.data = base64ToU8(m.data); self.render.update(m); }
        else if (m.t === 'close') { self.activeSession = false; setStatus(self, '连接关闭', '#e0a030'); if (next) next(null); }
        else if (m.t === 'error') { self.activeSession = false; setStatus(self, '错误:' + m.message, '#e66'); if (next) next(m); }
      };
      ws.onclose = function () { self.activeSession = false; setStatus(self, 'WS 断开', '#e0a030'); };
    }
  };
  function base64ToU8(b64) { var s = atob(b64), a = new Uint8Array(s.length); for (var i = 0; i < s.length; i++) a[i] = s.charCodeAt(i); return a; }
  function setStatus(c, t, col) { if (c.statusEl) { c.statusEl.textContent = t; c.statusEl.style.color = col || '#aaa'; } }
  function markFocus() { document.querySelectorAll('.pane').forEach(function (p) { p.classList.remove('active'); }); if (focused && focused.paneEl) focused.paneEl.classList.add('active'); }

  // 全局键盘 → 聚焦分身
  window.addEventListener('keydown', function (e) { if (!focused || !focused.activeSession) return; focused.emit({ t: 'scancode', code: Mstsc.scancode(e), isPressed: true }); e.preventDefault(); });
  window.addEventListener('keyup', function (e) { if (!focused || !focused.activeSession) return; focused.emit({ t: 'scancode', code: Mstsc.scancode(e), isPressed: false }); e.preventDefault(); });

  Mstsc.client = { create: function (canvas) { return new Client(canvas); } };
})();
