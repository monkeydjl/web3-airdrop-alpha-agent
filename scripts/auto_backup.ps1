# ═════════════════════════════════════════════════════════════════
# Web3 Airdrop Alpha - 自动备份脚本 (PowerShell)
# ═════════════════════════════════════════════════════════════════
# 用途: 每天定时备份 PostgreSQL 生产数据库
# 计划任务: 每日 02:00 执行（由 Windows 计划任务触发）
# 依赖: Docker Desktop 运行中，容器 airdrop-db 在线
# 输出: <ProjectRoot>\backups\auto\airdrop_auto_<时间戳>.zip
# 保留策略: 最近 N 天（默认 7）
# ═════════════════════════════════════════════════════════════════
#
# 2026-08-24 修了三个问题（都实测复现过）：
#
# 1. 【每次失败留一个空目录】旧版在检查容器之前就 New-Item 建了带时间戳的
#    目录。容器不在线时脚本 exit 1，目录留在盘上；而清理逻辑只删 *.zip，
#    永远不碰这些目录 —— 于是**每天失败一次就多一个空目录，无人回收**。
#    实测：Docker 未运行时跑一次，`backups\auto\airdrop_auto_<ts>\` 空目录残留。
#    修法：目录延后到「容器确认在线之后」才建，并且所有失败路径都走
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

# 日志目录必须先建（下面每条失败分支都要写日志）。
# 注意这里只建到 backups\auto —— 带时间戳的工作目录留到容器检查通过后再建，
# 否则每次失败都会留下一个没人回收的空目录。
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

function Write-Log {
    param([string]$Message)
    $Line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Message"
    Write-Host $Line
    Add-Content -Path $LogFile -Value $Line
}

function Remove-BackupWorkDir {
    <#
        删掉本次运行自己建的工作目录。只在目录存在且为空时删 ——
        里面已经有 dump 文件的话保留下来，那是可用的备份，
        丢掉它比留一个目录严重得多。
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

Write-Log "备份开始: $BackupName"

Remove-StaleWorkDirs

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

# 4. 写入备份信息
$info = @"
Backup: $BackupName
Date: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
Database: PostgreSQL (airdrop-db)
Files:
$(Get-ChildItem $BackupPath | Select-Object Name, @{N = "Size"; E = { "{0:N0} bytes" -f $_.Length } } | Format-Table -AutoSize | Out-String)
"@
$info | Out-File "$BackupPath\backup-info.txt" -Encoding UTF8

# 5. 压缩备份
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
    # 关键：不删源目录。dump 文件本身就是可用的备份，
    # 压缩只是打包步骤，不能因为打包失败把备份也一起丢掉。
    Write-Log "警告: 未生成压缩包，原始 dump 文件保留在 $BackupPath（可直接用 pg_restore 恢复）"
}

# 6. 清理旧备份（保留最近 N 天）
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

if (-not $compressed) {
    Write-Log "备份流程结束（有告警：未压缩）"
    exit 4
}

Write-Log "备份成功! 文件: $BackupName.zip"
Write-Log "备份流程结束"
exit 0
