# ═════════════════════════════════════════════════════════════════
# Web3 Airdrop Alpha - 自动备份脚本 (PowerShell)
# ═════════════════════════════════════════════════════════════════
# 用途: 每天定时备份数据库(按 .env 的 DB_BACKEND 路由)
# 计划任务: 每日 02:00 执行（由 Windows 计划任务触发）
# 依赖: postgres 模式需要 Docker Desktop 运行中且容器 airdrop-db 在线;
#       sqlite 模式需要 backend\venv 的 Python(或 PATH 上的 python)
# 输出: <ProjectRoot>\backups\auto\airdrop_auto_<时间戳>.zip
# 保留策略: 最近 N 天（默认 7）
# ═════════════════════════════════════════════════════════════════
#
# 2026-10-01 修了一个「备份成功但备的是错库」的问题（实测复现过）：
#
# 4. 【脚本钉死在 PostgreSQL,而活动库已切回 SQLite】旧版用途写死
#    「备份 PostgreSQL 生产数据库」,无条件走 airdrop-db 容器 pg_dump。
#    但 .env 的 DB_BACKEND=sqlite,真实活动库是 backend\data\airdrop.db
#    （31MB,每天在被写入）;容器里的 PG 是 9 月切库前的陈旧数据
#    （raw_projects 924 行 vs 活动库 1314 行）。结果:日志每天打印
#    「备份成功!」,而**在用的库没有任何在生效的定时备份** ——
#    2026-08-24 §12.5「备份过期副本还报成功」事故的复活变体。
#    修法:读 .env 的 DB_BACKEND 路由。
#      - sqlite（缺省,与 app config 默认一致）:解析 DB_PATH 定位库文件
#        （相对路径优先按 backend\ 解析 —— 服务进程的 CWD 在 backend\,
#        这正是 Start.bat 的启动方式;backend\ 下没有才回退项目根,顺序
#        不能反,因为项目根的 data\airdrop.db 是过期副本）,用 Python
#        sqlite3 的**在线 backup API** 拷贝（对 WAL 模式的活库安全,
#        不需要停服务,比文件复制可靠）,拷完跑 PRAGMA integrity_check
#        校验,通过才算成功。
#      - postgres:原有 docker pg_dump 流程原样保留（下面的
#        2026-08-24 三个修复全部继续生效）。
#      - .env 没有 DB_BACKEND 时按 sqlite 处理（app 的默认值也是它）。
#      - 不再猜文件名:DB_PATH 未设置或两处都找不到 → exit 5 报错,
#        沿用 backup.sh「不猜其它文件名」的同一契约。
#      - SQLite 校验失败（exit 6）时清掉自己的工作目录 —— 里面的半个
#        库不是可用备份;这与 PG 的 SQL-dump 失败路径（exit 3 保留目录,
#        里面有可用的 custom dump）方向相反,是有意的。
#
# 2026-08-24 修了三个问题（都实测复现过）：
#
# 1. 【每次失败留一个空目录】旧版在检查容器之前就 New-Item 建了带时间戳的
#    目录。容器不在线时脚本 exit 1，目录留在盘上；而清理逻辑只删 *.zip，
#    永远不碰这些目录 —— 于是**每天失败一次就多一个空目录，无人回收**。
#    实测：Docker 未运行时跑一次，`backups\auto\airdrop_auto_<ts>\` 空目录残留。
#    修法：目录延后到「前置检查通过之后」才建，并且所有失败路径都走
#    Remove-BackupWorkDir 清掉自己建的目录。
#
# 2. 【压缩失败会静默丢掉备份，日志还说文件留着】旧版无论 Compress-Archive
#    成功与否都 `Remove-Item -Recurse -Force $BackupPath`，然后在找不到 zip 时
#    记一句「备份文件保留在 $BackupPath」—— 那个目录上一行刚被删掉。
#    结果是：**dump 没了、zip 没了、日志告诉你文件还在**。
#    这比"备份失败"更糟：失败会被人发现，一句假的成功不会。
#    修法：压缩用 -ErrorAction Stop，只有确认 zip 存在且非空才删源目录；
#    压缩失败时**保留**源目录并明确记「未压缩，原始文件在 <路径>」。
#
# 3. 【一段死代码指向不存在的产物】旧版建了个 $compress 哈希表，
#    DestinationPath 写的是 .tar.gz，但从没被用过 —— 实际调用是 .zip。
#    读的人会以为产物是 tar.gz。已删除。
#
# ⚠️ 【本文件必须保存为带 BOM 的 UTF-8】改这个文件时最容易踩的坑，
#    而且它的表现是**静默不执行**，不是报错：
#
#    Windows PowerShell 5.1 在文件没有 BOM 时，按系统 ANSI 代码页
#    （简体中文机器 = GBK）解码脚本。GBK 是双字节编码，任何 >= 0x80 的字节
#    都会无条件吃掉紧随其后的一个字节 —— 包括 ASCII 引号。
#    而 UTF-8 中文字符是 3 字节（奇数），于是"结束引号会不会被吃掉"
#    取决于它前面有多少字节的中文：
#
#        "中"     3 字节（奇） → 引号被吃
#        "中文"   6 字节（偶） → 引号保留
#        "中文字" 9 字节（奇） → 引号被吃
#
#    引号一被吃掉，字符串就不闭合，往下把几十行代码全吞进一个字面量 ——
#    **而且语法完全合法**，解析器报 0 个错误。表现是脚本跳过那几十行、
#    返回 exit 0 说"备份成功"，实际什么都没做。
#
#    2026-08-24 实测撞过一次：本文件原本是 UTF-16LE，重写时存成 UTF-8 无 BOM，
#    于是执行从第 20 行直接跳到第 153 行，日志文件都没建出来还是 exit 0。
#
#    这条奇偶性意味着「今天没事」不等于安全 —— 加一个字就会翻转。
#    已由 `scripts/check_encoding.py` 的第四型检查在 pre-commit / CI 拦住。
# ═════════════════════════════════════════════════════════════════

param(
    [string]$ProjectRoot = "D:\Github\Web3 Airdrop Alpha Agent System",
    [int]$RetentionDays = 7
)

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$BackupDir = Join-Path $ProjectRoot "backups\auto"
$BackupName = "airdrop_auto_$Timestamp"
$BackupPath = Join-Path $BackupDir $BackupName
$LogFile = Join-Path $ProjectRoot "backups\auto_backup.log"
$EnvFile = Join-Path $ProjectRoot ".env"

# 日志目录必须先建（下面每条失败分支都要写日志）。
# 注意这里只建到 backups\auto —— 带时间戳的工作目录留到前置检查通过后再建，
# 否则每次失败都会留下一个没人回收的空目录。
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

function Write-Log {
    param([string]$Message)
    $Line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Message"
    Write-Host $Line
    Add-Content -Path $LogFile -Value $Line
}

function Get-DotEnvValue {
    <#
        读 .env 里某个键的值。契约与 backup.sh 的解析管道逐条对齐:
        多行取**最后一条**（Select-Object -Last 1）、值里可以带 =（-split 2 段）、
        去掉两端空白（Trim，含 \r）。找不到键返回空串。
    #>
    param([string]$Key)
    if (-not (Test-Path $EnvFile)) { return "" }
    $line = Get-Content -Path $EnvFile -Encoding UTF8 |
        Where-Object { $_ -match "^$Key=" } |
        Select-Object -Last 1
    if ($line) { return (($line -split "=", 2)[1]).Trim() }
    return ""
}

function Remove-BackupWorkDir {
    <#
        删掉本次运行自己建的工作目录。只在目录存在且为空时删 ——
        里面已经有 dump 文件的话保留下来，那是可用的备份，
        丢掉它比留一个目录严重得多。
        （例外:SQLite 校验失败路径**不走这里**,那个目录里只有半个废库,
        由该分支显式整目录删除 —— 见头注释 2026-10-01 一节。）
    #>
    if (-not (Test-Path $BackupPath)) { return }
    $items = @(Get-ChildItem $BackupPath -Force -ErrorAction SilentlyContinue)
    if ($items.Count -eq 0) {
        Remove-Item -Recurse -Force $BackupPath -ErrorAction SilentlyContinue
        Write-Log "已清理本次空工作目录: $BackupName"
    }
    else {
        Write-Log "工作目录非空（$($items.Count) 个文件），保留: $BackupPath"
    }
}

function Remove-StaleWorkDirs {
    <#
        回收历史上遗留的空工作目录。

        这个函数存在的理由就是上面第 1 条 bug：旧版每次失败留一个空目录，
        而清理逻辑只删 *.zip。修好新代码不会让老垃圾自己消失，
        所以补一次回收 —— 只删**空**目录，非空的一律不碰。
    #>
    $stale = @(
        Get-ChildItem $BackupDir -Directory -Filter "airdrop_auto_*" -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -ne $BackupPath } |
            Where-Object { @(Get-ChildItem $_.FullName -Force -ErrorAction SilentlyContinue).Count -eq 0 }
    )
    foreach ($dir in $stale) {
        Remove-Item -Recurse -Force $dir.FullName -ErrorAction SilentlyContinue
        Write-Log "清理遗留空目录: $($dir.Name)"
    }
    if ($stale.Count -gt 0) {
        Write-Log "共清理 $($stale.Count) 个遗留空目录（旧版失败路径留下的）"
    }
}

function Invoke-CompressAndCleanup {
    <#
        共享的收尾:写 info → 压缩 → 成功删源目录/失败保留 → 清理旧 zip。
        返回 $true=压缩成功。2026-08-24 修复 2 的契约在这里单一实现,
        sqlite / postgres 两条路径共用,不许分叉出第二份压缩逻辑。
    #>
    param([string]$InfoText)
    $InfoFile = Join-Path $BackupPath "backup-info.txt"
    $InfoText | Out-File -FilePath $InfoFile -Encoding UTF8

    #    只有确认 zip 真的生成且非空，才删源目录。
    #    旧版无条件删源目录，压缩失败就等于把备份丢了 —— 而日志还说文件留着。
    Write-Log "压缩备份..."
    $ZipPath = "$BackupPath.zip"
    $compressed = $false
    try {
        Compress-Archive -Path $BackupPath -DestinationPath $ZipPath -CompressionLevel Optimal -Force -ErrorAction Stop
        $zip = Get-Item $ZipPath -ErrorAction Stop
        if ($zip.Length -le 0) { throw "压缩包大小为 0" }
        $compressed = $true
        Write-Log "压缩完成: $ZipPath ($($zip.Length) bytes)"
    }
    catch {
        Write-Log "错误: 压缩失败（$($_.Exception.Message)）"
    }

    if ($compressed) {
        Remove-Item -Recurse -Force $BackupPath
    }
    else {
        # 关键：不删源目录。里面的产物本身就是可用的备份，
        # 压缩只是打包步骤，不能因为打包失败把备份也一起丢掉。
        Write-Log "警告: 未生成压缩包，原始备份文件保留在 $BackupPath（未压缩，可直接使用）"
    }

    # 清理旧备份（保留最近 N 天）
    Write-Log "清理 $RetentionDays 天前的旧备份..."
    $cutoff = (Get-Date).AddDays(-$RetentionDays)
    Get-ChildItem $BackupDir -Filter "airdrop_auto_*.zip" | Where-Object {
        $_.CreationTime -lt $cutoff
    } | ForEach-Object {
        Remove-Item $_.FullName -Force
        Write-Log "删除旧备份: $($_.Name)"
    }
    $remaining = (Get-ChildItem $BackupDir -Filter "airdrop_auto_*.zip" | Measure-Object).Count
    Write-Log "清理完成，保留 $remaining 个备份"

    return $compressed
}

Write-Log "备份开始: $BackupName"

Remove-StaleWorkDirs

# ── 路由:按 .env 的 DB_BACKEND 决定备份哪条链 ────────────────────
# 没有 .env 或没有这个键时按 sqlite 处理 —— 与 app config 的默认值一致,
# 宁可备一个不存在的 sqlite 文件而报错,也不要静默去备一个可能已废弃的
# PG 容器（2026-10-01 事故的教训就是方向反了）。
$DbBackend = Get-DotEnvValue "DB_BACKEND"
if ([string]::IsNullOrWhiteSpace($DbBackend)) {
    $DbBackend = "sqlite"
    Write-Log "DB_BACKEND 未设置,按缺省 sqlite 处理"
}
Write-Log "DB_BACKEND=$DbBackend"

if ($DbBackend -eq "postgres") {

    # 1. 检查 Docker 和容器状态
    $dockerRunning = docker ps --filter "name=airdrop-db" --format "{{.Names}}" 2>$null
    if (-not $dockerRunning) {
        Write-Log "错误: airdrop-db 容器未运行，跳过备份（未建立工作目录）"
        exit 1
    }
    Write-Log "容器 airdrop-db 在线"

    # 容器确认在线之后才建工作目录
    New-Item -ItemType Directory -Force -Path $BackupPath | Out-Null

    # 2. pg_dump - custom 格式（最快恢复，支持 pg_restore 选择性恢复）
    Write-Log "导出 custom 格式备份..."
    docker exec airdrop-db pg_dump -U airdrop -d airdrop --no-owner --no-privileges -F c -f /tmp/airdrop_auto.dump
    if ($LASTEXITCODE -ne 0) {
        Write-Log "错误: pg_dump custom 失败"
        Remove-BackupWorkDir
        exit 2
    }
    docker cp "airdrop-db:/tmp/airdrop_auto.dump" "$BackupPath\airdrop_pg.dump"
    docker exec airdrop-db rm -f /tmp/airdrop_auto.dump
    Write-Log "custom 格式备份完成: $(Get-Item "$BackupPath\airdrop_pg.dump" | Select-Object -ExpandProperty Length) bytes"

    # 3. pg_dump - SQL 格式（可直接查看/恢复）
    Write-Log "导出 SQL 格式备份..."
    docker exec airdrop-db pg_dump -U airdrop -d airdrop --no-owner --no-privileges -f /tmp/airdrop_auto.sql
    if ($LASTEXITCODE -ne 0) {
        Write-Log "错误: pg_dump SQL 失败"
        Remove-BackupWorkDir
        exit 3
    }
    docker cp "airdrop-db:/tmp/airdrop_auto.sql" "$BackupPath\airdrop_pg.sql"
    docker exec airdrop-db rm -f /tmp/airdrop_auto.sql
    $sqlSize = (Get-Item "$BackupPath\airdrop_pg.sql" | Select-Object -ExpandProperty Length)
    Write-Log "SQL 格式备份完成: $sqlSize bytes"

    $info = @"
Backup: $BackupName
Date: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
Database: PostgreSQL (airdrop-db)
Files:
$(Get-ChildItem $BackupPath | Select-Object Name, @{N = "Size"; E = { "{0:N0} bytes" -f $_.Length } } | Format-Table -AutoSize | Out-String)
"@
    $compressed = Invoke-CompressAndCleanup -InfoText $info
}
else {

    # ── SQLite 路径 ──────────────────────────────────────────────
    # 1. 从 .env 解析 DB_PATH 定位库文件。相对路径优先按 backend\ 解析
    #    （服务进程 CWD 在 backend\,Start.bat 就是这么启动的）,
    #    backend\ 下没有才回退项目根 —— 顺序不能反:项目根的
    #    data\airdrop.db 是过期副本,先匹配到它就重演备错库事故。
    $DbPathRaw = Get-DotEnvValue "DB_PATH"
    if ([string]::IsNullOrWhiteSpace($DbPathRaw)) {
        Write-Log "错误: .env 未设置 DB_PATH（sqlite 模式必填,不猜默认文件名）"
        exit 5
    }
    $DbPathNorm = $DbPathRaw -replace "/", "\"
    $DbFileBackend = Join-Path $ProjectRoot ("backend\" + $DbPathNorm)
    $DbFileRoot = Join-Path $ProjectRoot $DbPathNorm
    if (Test-Path $DbFileBackend) {
        $DbFile = $DbFileBackend
        Write-Log "库文件（backend 相对路径）: $DbFile"
    }
    elseif (Test-Path $DbFileRoot) {
        $DbFile = $DbFileRoot
        Write-Log "警告: 库文件命中项目根相对路径 $DbFile —— backend\ 下没有同名文件。若这不是有意的,检查 DB_PATH 与服务 CWD 是否分家"
    }
    else {
        Write-Log "错误: DB_PATH=$DbPathRaw 在 backend\ 与项目根下都不存在 —— 不猜其它文件名"
        exit 5
    }

    # 2. 选 Python:优先 backend\venv（与被备份的系统同环境）,退而 PATH
    $Py = Join-Path $ProjectRoot "backend\venv\Scripts\python.exe"
    if (Test-Path $Py) {
        Write-Log "使用 venv Python: $Py"
    }
    else {
        $Py = "python"
        Write-Log "venv Python 不存在,退回 PATH 上的 python"
    }

    # 前置检查通过,才建工作目录（同 PG 路径的修复 1 契约）
    New-Item -ItemType Directory -Force -Path $BackupPath | Out-Null

    # 3. 在线备份 + 完整性校验。用 sqlite3 的 backup API 而不是文件复制:
    #    活库开着 WAL,复制文件可能拿到撕裂的一致点;backup API 由
    #    SQLite 自己保证页级一致,且不需要停服务。
    #    python 辅助代码写到系统 TEMP,用后即删 —— 放进工作目录会跟着
    #    压进备份 zip,恢复包里不该有可执行辅助文件。
    #    python 代码是纯 ASCII here-string,不经 PS 字符串转义。
    $PyScript = Join-Path $env:TEMP "airdrop_sqlite_backup_$Timestamp.py"
    @'
import os
import sqlite3
import sys

# 行为钉故障注入（TestAutoBackupDbBackendRouting）：在真备份前模拟
# 「备份或校验失败」路径，验证调用方的 exit 6 + 目录清理契约。
if os.environ.get("BACKUP_FAIL_INTEGRITY") == "1":
    print("SQLITE_BACKUP_FAIL injected")
    sys.exit(6)

src_path, dst_path = sys.argv[1], sys.argv[2]
if os.path.exists(dst_path):
    os.remove(dst_path)
try:
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dst_path)
    src.backup(dst)
    src.close()
    dst.close()
except Exception as exc:
    print("SQLITE_BACKUP_FAIL %s" % exc)
    sys.exit(6)
ver = sqlite3.connect(dst_path)
try:
    integrity = ver.execute("PRAGMA integrity_check").fetchone()[0]
    tables = ver.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
finally:
    ver.close()
if integrity != "ok":
    print("SQLITE_BACKUP_FAIL integrity=%s" % integrity)
    sys.exit(6)
print("SQLITE_BACKUP_OK integrity=ok tables=%d size=%d" % (tables, os.path.getsize(dst_path)))
sys.exit(0)
'@ | Out-File -FilePath $PyScript -Encoding ascii

    $DstDb = Join-Path $BackupPath "airdrop_sqlite_$Timestamp.db"
    Write-Log "SQLite 在线备份: $DbFile -> $DstDb"
    try {
        $pyOut = & $Py $PyScript $DbFile $DstDb 2>&1
        $pyExit = $LASTEXITCODE
    }
    catch {
        Write-Log "错误: 无法启动 Python（$($_.Exception.Message)）"
        Remove-Item -Recurse -Force $BackupPath -ErrorAction SilentlyContinue
        exit 7
    }
    foreach ($line in @($pyOut)) { if ($line) { Write-Log "  $line" } }
    Remove-Item -Force $PyScript -ErrorAction SilentlyContinue
    if ($pyExit -ne 0) {
        Write-Log "错误: SQLite 备份/校验失败（exit $pyExit）"
        # 半个库不是可用备份 —— 整目录删掉（与 PG SQL-fail 保留目录方向相反,见头注释）
        Remove-Item -Recurse -Force $BackupPath -ErrorAction SilentlyContinue
        Write-Log "已清理失败的工作目录: $BackupName"
        exit 6
    }

    $info = @"
Backup: $BackupName
Date: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
Database: SQLite ($DbFile)
Files:
$(Get-ChildItem $BackupPath | Select-Object Name, @{N = "Size"; E = { "{0:N0} bytes" -f $_.Length } } | Format-Table -AutoSize | Out-String)
"@
    $compressed = Invoke-CompressAndCleanup -InfoText $info
}

if (-not $compressed) {
    Write-Log "备份流程结束（有告警：未压缩）"
    exit 4
}

Write-Log "备份成功! 文件: $BackupName.zip"
Write-Log "备份流程结束"
exit 0
