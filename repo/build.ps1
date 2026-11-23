<#
  一键构建发行包：嵌入式 Python + 依赖 + KaTeX + 程序主体 -> dist\AI批注\ -> zip
  用法：powershell -ExecutionPolicy Bypass -File .\build.ps1
#>
param([string]$Version = "0.3")
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$stage = Join-Path $root "dist\AI批注"
$zipPath = Join-Path $root "dist\AI批注-v$Version.zip"

Write-Host "[1/6] 准备目录" -ForegroundColor Cyan
if (Test-Path (Join-Path $root "dist")) { Remove-Item (Join-Path $root "dist") -Recurse -Force }
New-Item -ItemType Directory -Force -Path $stage, "$stage\python", "$stage\app", "$stage\书" | Out-Null

Write-Host "[2/6] 拷贝程序主体" -ForegroundColor Cyan
robocopy (Join-Path $root "app") (Join-Path $stage "app") /E /XD __pycache__ vendor /XF *.pyc /NFL /NDL /NJH /NJS | Out-Null
Copy-Item (Join-Path $root "启动.bat") $stage -Force
Copy-Item (Join-Path $root "使用说明.html") $stage -Force
Copy-Item (Join-Path $root "config.sample.json") (Join-Path $stage "config.json") -Force

Write-Host "[3/6] 下载嵌入式 Python" -ForegroundColor Cyan
$pyZip = Join-Path $env:TEMP "py_embed.zip"
Invoke-WebRequest "https://mirrors.huaweicloud.com/python/3.12.10/python-3.12.10-embed-amd64.zip" -OutFile $pyZip -UseBasicParsing
Expand-Archive $pyZip (Join-Path $stage "python") -Force
$pth = "python312.zip`n.`nLib\site-packages`nimport site`n"
Set-Content -Path (Join-Path $stage "python\python312._pth") -Value $pth -Encoding ASCII

Write-Host "[4/6] 安装 pip 与依赖" -ForegroundColor Cyan
$py = Join-Path $stage "python\python.exe"
$pip = Join-Path $env:TEMP "get-pip.py"
Invoke-WebRequest "https://bootstrap.pypa.io/get-pip.py" -OutFile $pip -UseBasicParsing
& $py $pip --no-warn-script-location | Out-Null
& $py -m pip install --disable-pip-version-check --no-cache-dir --no-warn-script-location `
    -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com `
    "pymupdf==1.24.14" pillow numpy websocket-client | Out-Null

Write-Host "[5/6] 下载前端依赖（KaTeX / marked）" -ForegroundColor Cyan
$vendor = Join-Path $stage "app\panel\vendor"
New-Item -ItemType Directory -Force -Path $vendor | Out-Null
$katexZip = Join-Path $env:TEMP "katex.zip"
Invoke-WebRequest "https://github.com/KaTeX/KaTeX/releases/download/v0.16.11/katex.zip" -OutFile $katexZip -UseBasicParsing
Expand-Archive $katexZip (Join-Path $env:TEMP "katex") -Force
Copy-Item (Join-Path $env:TEMP "katex\katex") (Join-Path $vendor "katex") -Recurse -Force
Invoke-WebRequest "https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js" -OutFile (Join-Path $vendor "marked.min.js") -UseBasicParsing

$book = Get-ChildItem (Join-Path $root "书") -Filter *.pdf -ErrorAction SilentlyContinue | Select-Object -First 1
if ($book) { Copy-Item $book.FullName (Join-Path $stage "书") -Force }

Write-Host "[6/6] 打包" -ForegroundColor Cyan
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zipPath -CompressionLevel Optimal -Force
$mb = [math]::Round(((Get-Item $zipPath).Length / 1MB), 1)
Write-Host "完成: $zipPath ($mb MB)" -ForegroundColor Green
