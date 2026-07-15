"use strict";
// ☯ 输入并发协作层 · 分身级输入仲裁（道并行而不相悖）
//
// 两条真相：
//  1) 不同分身(clone) = 不同 RDP 会话 = Windows 各自独立输入队列 ——「你操作你的，我操作我的」
//     天然隔离(两台完全隔离的电脑)，本仲裁器按 key 分桶，不同 key 永不互相阻塞。
//  2) 同一分身上多操作者(用户前端 canvas / AI 后端 UIA·PostMessage)会在 Windows 会话内交错抢占。
//     故对同一 key 采用「短租约轮替」：任一时刻至多一个持有者(holder)拥有输入权；
//     租约带 TTL 自动过期(操作者离场不会永久占用)，高优先级可抢占低优先级(用户默认高于 Agent，
//     用户随时能接管/协助/纠偏)。同优先级则先到先得，直至释放或过期。
//
// 纯内存、无副作用、可注入时钟——便于单测与嵌入隧道 HTTP 面。

const HUMAN = "human";
const AGENT = "agent";
const _PRIORITY = { [HUMAN]: 100, [AGENT]: 50 };

function priorityOf(owner, explicit) {
  if (typeof explicit === "number") return explicit;
  return _PRIORITY[owner && owner.kind] != null ? _PRIORITY[owner.kind] : 10;
}

class InputArbiter {
  constructor(opts) {
    opts = opts || {};
    this._ttl = opts.defaultTtlMs || 4000;
    this._now = opts.now || (() => Date.now());
    this._holders = new Map(); // key → { ownerId, kind, priority, expiresAt, since }
  }

  _live(key) {
    const h = this._holders.get(key);
    if (!h) return null;
    if (h.expiresAt <= this._now()) {
      this._holders.delete(key);
      return null;
    }
    return h;
  }

  // 申请/续租某分身的输入权。owner = { id, kind:'human'|'agent' }。
  // 返回 { granted, holder, reason }。granted=false 时 holder 为当前占用者(供前端提示"AI 正在操作")。
  acquire(key, owner, opts) {
    opts = opts || {};
    const now = this._now();
    const ttl = opts.ttlMs || this._ttl;
    const prio = priorityOf(owner, opts.priority);
    const cur = this._live(key);

    if (cur && cur.ownerId !== owner.id) {
      // 被他人持有：仅严格更高优先级可抢占（同级先到先得，避免用户与 Agent 抖动互抢）。
      if (prio <= cur.priority) {
        return { granted: false, holder: this._pub(key, cur), reason: "held" };
      }
    }
    const h = {
      ownerId: owner.id,
      kind: owner.kind || AGENT,
      priority: prio,
      since: (cur && cur.ownerId === owner.id) ? cur.since : now,
      expiresAt: now + ttl,
    };
    const preempted = cur && cur.ownerId !== owner.id ? this._pub(key, cur) : null;
    this._holders.set(key, h);
    return { granted: true, holder: this._pub(key, h), preempted };
  }

  // 释放（仅持有者本人可释放；非持有者调用无副作用）。
  release(key, ownerId) {
    const cur = this._live(key);
    if (cur && cur.ownerId === ownerId) {
      this._holders.delete(key);
      return true;
    }
    return false;
  }

  holder(key) {
    const cur = this._live(key);
    return cur ? this._pub(key, cur) : null;
  }

  // 判定某操作者此刻是否可向该分身注入输入（前端/后端注入前先问）。
  canInput(key, ownerId) {
    const cur = this._live(key);
    return !cur || cur.ownerId === ownerId;
  }

  list() {
    const out = [];
    for (const key of this._holders.keys()) {
      const cur = this._live(key);
      if (cur) out.push(this._pub(key, cur));
    }
    return out;
  }

  _pub(key, h) {
    return {
      key, ownerId: h.ownerId, kind: h.kind, priority: h.priority,
      since: h.since, expiresAt: h.expiresAt, ttlLeft: Math.max(0, h.expiresAt - this._now()),
    };
  }
}

module.exports = { InputArbiter, HUMAN, AGENT };
