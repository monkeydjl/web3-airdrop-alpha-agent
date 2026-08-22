# ═════════════════════════════════════════════════════════════════
# Web3 Airdrop Alpha - 自动备份脚本 (PowerShell)
# ═════════════════════════════════════════════════════════════════
# 用途: 每天定时备份 PostgreSQL 生产数据库
# 计划任务: 每日 02:00 执行（由 Windows 计划任务触发）
# 依赖: Docker Desktop 运行中，容器 airdrop-db 在线
# 输出: d:\Github\Web3 Airdrop Alpha Agent System\backups\auto\
# 保留策略: 最近 7 天备份
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

# 确保备份目录存在
New-Item -ItemType Directory -Force -Path $BackupPath | Out-Null

function Write-Log {
    param([string]$Message)
    $Line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Message"
    Write-Host $Line
    Add-Content -Path $LogFile -Value $Line
}

Write-Log "备份开始: $BackupName"

# 1. 检查 Docker 和容器状态
$dockerRunning = docker ps --filter "name=airdrop-db" --format "{{.Names}}" 2>$null
if (-not $dockerRunning) {
    Write-Log "错误: airdrop-db 容器未运行，跳过备份"
    exit 1
}
Write-Log "容器 airdrop-db 在线"

# 2. pg_dump - custom 格式（最快恢复，支持 pg_restore 选择性恢复）
Write-Log "导出 custom 格式备份..."
docker exec airdrop-db pg_dump -U airdrop -d airdrop --no-owner --no-privileges -F c -f /tmp/airdrop_auto.dump
if ($LASTEXITCODE -ne 0) {
    Write-Log "错误: pg_dump custom 失败"
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
$(Get-ChildItem $BackupPath | Select-Object Name, @{N="Size";E={"{0:N0} bytes" -f $_.Length}} | Format-Table -AutoSize | Out-String)
"@
$info | Out-File "$BackupPath\backup-info.txt" -Encoding UTF8

# 5. 压缩备份
Write-Log "压缩备份..."
$compress = @{
    Path = $BackupPath
    DestinationPath = "$BackupPath.tar.gz"
    CompressionLevel = "Optimal"
}
Compress-Archive -Path $BackupPath -DestinationPath "$BackupPath.zip" -CompressionLevel Optimal
Remove-Item -Recurse -Force $BackupPath
Write-Log "压缩完成: $BackupPath.zip"

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

# 7. 验证备份完整性
try {
    $testZip = Get-ChildItem "$BackupPath.zip" -ErrorAction Stop
    Write-Log "备份成功! 文件: $($testZip.Name), 大小: $($testZip.Length) bytes"
} catch {
    Write-Log "警告: 未找到压缩包，备份文件保留在 $BackupPath"
}

Write-Log "备份流程结束"
exit 0