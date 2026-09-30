# Windows 脚本的行为钉：Stop.bat 的两个潜伏缺陷与编码门禁的方向翻转

> 配套：`backend/tests/test_shell_scripts.py`（`TestStopBatBehavior` /
> `TestAutoBackupBehavior`）、`scripts/check_encoding.py`（五型）、
> `backend/tests/test_encoding_mojibake.py`。同类复盘：
> `testing-default-db-cleanliness.md`（洁净度快照）、
> `ENCODING_REPAIR.md`（编码五型总目录）。

## 0. 一句话版本

给 `Stop.bat` / `auto_backup.ps1` 补沙箱行为钉时，钉子挖出了被测对象的
**两个真实缺陷**（Stop.bat 带 BOM、`chcp 65001` + UTF-8 中文注释让 cmd
解析器字节错位并静默中断——前端循环从未运行过），顺带发现编码守卫
`check_encoding.py` 对批处理的方向是**反的**（要求中文批处理加 BOM，
而 BOM 正是毒药）。修复两者并把守卫规则翻转为五型。

时间线：2026-09-30。三条教训各自独立成立，但全部指向同一句话——
**「静态门禁绿」和「行为正确」是两件不同的事，而 harness 自己的
保真度决定行为钉的证词可不可信。**

## 1. 起点：静态门禁的空档

`TestWindowsBatchScripts` 对 Stop.bat 只有静态判据（`findstr ":8002"`
在代码行上、LISTENING 过滤在同条件行上）。这些判据全绿，但它们只能
证明「字符串存在于脚本里」，证明不了：

- 那段管道**真的会跑**（脚本可能在更早的地方就已经断了）；
- 管道的过滤结果**真的是预期的进程集合**；
- 脚本真的会执行到最后（静默中断不产生任何静态信号）。

`auto_backup.ps1` 更是只有静态门禁，零行为验证。

## 2. 挖出缺陷的经过

### 2.1 第一个拦截：netstat shim 没 .cmd 扩展名

行为钉先给 shim 做了**接管预检**（沙箱 PATH 直接调一次 netstat，
确认输出是假数据再跑被测脚本）。预检当场拦下：cmd 按 PATHEXT
解析命令，无扩展名的 shim 文件直接落空，跑的是 System32 真 netstat
——输出全是真实 PID。

**没有这层预检的后果**：Stop.bat 会按真实端口表对真实 LISTENING PID
执行 taskkill——开发者自己的后端进程。预检不是仪式，是安全栏。

### 2.2 第二个拦截：BOM 毒化 @echo off

修好扩展名后回显输出显示 `\ufeff@echo off` 被当成陌生命令——
**Stop.bat 一直带着 UTF-8 BOM**，`@echo off` 从未生效，整个脚本
以回显模式逐行执行。能跑，但解析行为已经变了。

### 2.3 实锤中断：chcp 65001 救不了

剥掉 BOM 后脚本仍在第一个 taskkill 后静默截断，第二个循环（前端
:3002）从未运行。stderr 给出实锤：

```
'——' is not recognized as an internal or external command
```

注释里的中文破折号被当成命令执行——`chcp 65001` 就写在脚本第 2 行，
仍然炸了。结论：cmd 逐字节解析批处理文件、没有代码页协商；
UTF-8 中文（3 字节/字）让后续行的解析偏移错位；chcp 只影响控制台
输出代码页，不影响解析器读文件的方式。

**最冷的注脚**：修复前 Stop.bat 每次运行都打印
`[OK] Backend service stopped` / `[OK] Frontend service stopped`，
而前端循环从未执行过——「跑成功了但什么都没做」的又一次重演，
与 test_shell_scripts.py 模块 docstring 里三个 2026-08-24 案例同型。

### 2.4 修复

Stop.bat 重写为纯 ASCII：英文注释、移除 `chcp 65001`、剥 BOM，
逻辑（两道 findstr 管道、taskkill 参数）逐字保持。补静态钉
`test_stop_bat_has_no_bom`，并在注释里写明与 PowerShell 的镜像规则
（见 §3）。

## 3. 守卫方向翻转：四型 → 五型

`check_encoding.py` 的四型规则原本是
`BOM_REQUIRED_SUFFIXES = {".ps1", ".psm1", ".bat", ".cmd"}`——
「含中文的 Windows 脚本必须有 BOM」。这对 PowerShell 是对的
（PS 5.1 无 BOM 按 GBK 解码，引号奇偶性陷阱，见 ENCODING_REPAIR.md），
对批处理是**反的**：BOM 毒化第一行、中文毒化解析，唯一安全形态是
纯 ASCII。也就是说守卫在把未来的中文批处理往刚炸过的地雷上引——
Stop.bat 若按守卫的指引加 BOM，§2 的缺陷会更早爆发。

翻转（守卫 + 测试同步）：

- `BOM_REQUIRED_SUFFIXES` 收窄为 `{".ps1", ".psm1"}`；
- 新增 `ASCII_ONLY_SUFFIXES = {".bat", ".cmd"}`，`main()` 增加五型
  检测（BOM 或任何 > 0x7F 字节即报，带首违行号/上下文）与独立
  报告块（机制 + 修法：纯 ASCII 重写，中文说明移 .md）；
- 测试侧：四型范围断言翻转 `.bat/.cmd` 期望；新增五型端到端
  （非 ASCII/带 BOM 拦、纯 ASCII 放——防「判据没接进主流程」的
  变异盲区，该盲区在四型上真实发生过）、镜像对照（同一份中文内容，
  PowerShell 必须 BOM / 批处理禁 BOM）、全仓实测
  `test_repo_batch_scripts_are_pure_ascii`；
- `.pre-commit-config.yaml` 注释同步五型（`files` 正则本就含
  bat/cmd，触发面无需改）。

## 4. harness 教训（行为钉方法论）

三条，都花了实打实的调试轮次才换来：

1. **shim 扩展名**：cmd 按 PATHEXT 解析，`netstat` 与 `netstat.cmd`
   不是同一个名字。无扩展名 shim = shim 不存在 = 真命令上场。
   防线是接管预检（先调一次假命令确认生效）。
2. **for 体内裸调 .cmd 会移交控制权**：调用者的 for 循环就地终止，
   与 shim 以 `exit /b` / `goto :eof` / 自然结束收尾无关（六组变体
   实测）；`call` 前缀能救，但那是 harness 的补丁不是被测对象的
   行为。正解是**不 shim 那个命令**：taskkill 不拦，让真 .exe 跑在
   不可能存在的 PID 上（Windows PID 恒为 4 的倍数，假数据全取
   非 4 倍数），断言证据改用被测脚本自己的回显行。保真被测对象
   的执行语义，比拦截一切外部命令更重要。
3. **cmd shim 必须 CRLF 且不得二次翻译**：if/for 块对仅 LF 的行为
   不可靠；而 shim 源码字符串里已含 `\r\n` 时再走 `write_text(newline=)`
   会叠成 `\r\r\n`（文件隔行出空行，块行为诡异）。写入用字节模式，
   先把体内行尾归一再统一转换。

另外两条经验：`_run_one` 那次的「摘要行只剩 1 error 无从诊断」在
这里重演了一次——给 harness 留存中间产物（调用日志、完整输出）
的功夫永远不白花；以及调试批处理时驱动脚本自身的 Bash 习惯
（`>/dev/null`）会静默毒化实验，对照实验组要做足（真实 shim vs
最小变体）才能把变量隔离干净。

## 5. 终态

- Stop.bat：纯 ASCII、无 BOM、无 chcp；行为钉断言两循环跑完且
  kill 目标恰为 LISTENING 集合。
- auto_backup.ps1：BOM ✓（必须），行为钉覆盖容器离线 / custom / SQL
  失败 / 成功四条退出路径与工作目录清理契约（压缩失败路径依赖
  真实 Compress-Archive 失败，沙箱无法可靠注入，静态门禁盖住存在性）。
- check_encoding.py：五型上线，全仓 817 文件通过；
  `test_encoding_mojibake` 46/46（直跑 + xdist）。
- 酸测 / parity / ruff 双腿全绿。
