<#
.SYNOPSIS
    把「勇者邦邦」打包成 exe。

.DESCRIPTION
    首次运行会自动在项目下创建 .venv-build 虚拟环境并安装 maafw / Pillow / scipy /
    PyInstaller，然后调用 PyInstaller 打包。默认产出单文件 dist\勇者邦邦.exe。

.PARAMETER OneDir
    改用目录版（dist\勇者邦邦\勇者邦邦.exe）。启动比单文件快很多，
    适合放在本机长期使用；分发给别人时把整个文件夹一起拷过去。

.PARAMETER Clean
    打包前清空 PyInstaller 缓存（build\Myhero、dist\）。

.PARAMETER Console
    保留控制台窗口，方便查看 Python 报错，用于排错。

.PARAMETER Python
    指定用于打包的 Python 解释器路径，默认使用 .venv-build 或系统 python。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\build_exe.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\build_exe.ps1 -OneDir -Clean
#>
[CmdletBinding()]
param(
    [switch]$OneDir,
    [switch]$Clean,
    [switch]$Console,
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $Root ".venv-build"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

function Write-Step([string]$Message) {
    Write-Host "==> $Message" -ForegroundColor Cyan
}

# ---------------------------------------------------------------- 解释器 ---
function Resolve-Python() {
    if ($Python) {
        if (-not (Test-Path -LiteralPath $Python)) {
            throw "指定的 Python 不存在：$Python"
        }
        return (Resolve-Path -LiteralPath $Python).Path
    }
    if (Test-Path -LiteralPath $VenvPython) {
        return $VenvPython
    }

    Write-Step "创建打包用虚拟环境 .venv-build"
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        & $launcher.Source -3 -m venv $VenvDir
    }
    else {
        $fallback = Get-Command python -ErrorAction SilentlyContinue
        if (-not $fallback) {
            throw "找不到 Python，请先安装 Python 3.10+ 或指定 -Python 参数"
        }
        & $fallback.Source -m venv $VenvDir
    }
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        throw "虚拟环境创建失败：$VenvPython"
    }
    return $VenvPython
}

$PythonExe = Resolve-Python
Write-Step "使用解释器：$PythonExe"

# ---------------------------------------------------------------- 依赖 -----
Write-Step "安装依赖（maafw / Pillow / scipy / PyInstaller）"
& $PythonExe -m pip install --disable-pip-version-check --quiet --upgrade pip
& $PythonExe -m pip install --disable-pip-version-check --quiet -r (Join-Path $Root "requirements.txt")
& $PythonExe -m pip install --disable-pip-version-check --quiet "pyinstaller>=6.6"
if ($LASTEXITCODE -ne 0) {
    throw "依赖安装失败，请检查网络后重试"
}

# ---------------------------------------------------------------- 打包 -----
$distDir = Join-Path $Root "dist"
$workDir = Join-Path $Root "build"
if ($Clean) {
    Write-Step "清理旧的构建产物"
    Remove-Item -LiteralPath (Join-Path $workDir "Myhero"), $distDir -Recurse -Force -ErrorAction SilentlyContinue
}

$env:MYHERO_ONEFILE = if ($OneDir) { "0" } else { "1" }
$env:MYHERO_CONSOLE = if ($Console) { "1" } else { "0" }
Write-Step ("开始打包：" + $(if ($OneDir) { "目录版" } else { "单文件版" }))

& $PythonExe -m PyInstaller (Join-Path $Root "Myhero.spec") `
    --noconfirm `
    --distpath $distDir `
    --workpath $workDir
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller 打包失败"
}

# ---------------------------------------------------------------- 结果 -----
$appName = if ($env:MYHERO_NAME) { $env:MYHERO_NAME } else { "勇者邦邦" }
$target = if ($OneDir) { Join-Path $distDir (Join-Path $appName "$appName.exe") } else { Join-Path $distDir "$appName.exe" }
if (-not (Test-Path -LiteralPath $target)) {
    throw "未找到打包结果：$target"
}

$size = [math]::Round((Get-Item -LiteralPath $target).Length / 1MB, 1)
Write-Host ""
Write-Host "打包完成：$target ($size MB)" -ForegroundColor Green
Write-Host "首次运行会在 exe 同级目录生成 config\ 与 debug\ 日志目录。"
