"use strict";
// 多实例桌面网格布局核单测：行列近似正方、格数恒 ≥ 分身数、空态兜底 1×1。
const { test } = require("node:test");
const assert = require("node:assert");
const { gridDims } = require("../grid-layout");

test("空态与单路: 恒 1×1", () => {
  assert.deepStrictEqual(gridDims(0), { cols: 1, rows: 1 });
  assert.deepStrictEqual(gridDims(1), { cols: 1, rows: 1 });
  assert.deepStrictEqual(gridDims(-3), { cols: 1, rows: 1 });
  assert.deepStrictEqual(gridDims(undefined), { cols: 1, rows: 1 });
});

test("常见分身数: 近似正方", () => {
  assert.deepStrictEqual(gridDims(2), { cols: 2, rows: 1 });
  assert.deepStrictEqual(gridDims(3), { cols: 2, rows: 2 });
  assert.deepStrictEqual(gridDims(4), { cols: 2, rows: 2 });
  assert.deepStrictEqual(gridDims(5), { cols: 3, rows: 2 });
  assert.deepStrictEqual(gridDims(6), { cols: 3, rows: 2 });
  assert.deepStrictEqual(gridDims(7), { cols: 3, rows: 3 });
  assert.deepStrictEqual(gridDims(9), { cols: 3, rows: 3 });
  assert.deepStrictEqual(gridDims(10), { cols: 4, rows: 3 });
  assert.deepStrictEqual(gridDims(16), { cols: 4, rows: 4 });
});

test("不变量: 1..64 路格数恒 ≥ 分身数且不过配一整行", () => {
  for (let n = 1; n <= 64; n++) {
    const { cols, rows } = gridDims(n);
    assert.ok(cols * rows >= n, `n=${n} 格数不足`);
    assert.ok(cols * (rows - 1) < n, `n=${n} 多配了一整行`);
  }
});

test("非整数入参: 向下取整", () => {
  assert.deepStrictEqual(gridDims(4.9), { cols: 2, rows: 2 });
  assert.deepStrictEqual(gridDims("3"), { cols: 2, rows: 2 });
});
