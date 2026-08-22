/**
 * 前端测试入口。
 *
 * 为什么不用 `node --test`：它会为每个测试文件 spawn 一个子进程，而本机沙箱
 * 下 spawn 直接 EPERM（实测 `errno: -4048`）。这里改成**在同一个进程里 import**
 * 每个测试文件，`node:test` 的 describe/it 照常注册与汇总，行为一致但不 spawn，
 * 因此本机和 CI 跑的是同一条路径 —— 不存在「本地能过、CI 不能」的差异。
 *
 * 加新测试文件时在下面的数组里补一行。刻意不做目录自动扫描：显式列表能让
 * 「文件写了但没被跑」这种失败一眼看见，自动扫描漏了反而是静默的。
 */

const FILES = ['./lib/download.test.ts'];

for (const f of FILES) {
  await import(f);
}
