$ErrorActionPreference = "Stop"
$versions = Join-Path $env:USERPROFILE ".workbuddy/binaries/node/versions"
$candidates = @()
if (Test-Path -LiteralPath "$versions/current" -PathType Leaf) {
  $v = (Get-Content -Raw -LiteralPath "$versions/current").Trim()
  if ($v -match '^[0-9][a-zA-Z0-9._-]*$') { $candidates += "$versions/$v/node.exe", "$versions/$v/bin/node.exe" }
}
$systemNode = Get-Command node.exe -ErrorAction SilentlyContinue
if ($systemNode) { $candidates += $systemNode.Source }
foreach ($nodePath in $candidates) {
  if (Test-Path -LiteralPath $nodePath -PathType Leaf) {
    & $nodePath -e 'process.exit(parseInt(process.versions.node)>=20 && require("node:fs").existsSync(require("node:path").join(require("node:path").dirname(process.execPath),"node_modules/npm/bin/npm-cli.js")) ? 0 : 1)'
    if ($LASTEXITCODE -eq 0) {
      if ($args.Count -eq 2 -and $args[0] -eq "env" -and $args[1] -eq "status") { & $nodePath "$PSScriptRoot/environment.js"; exit $LASTEXITCODE }
      & $nodePath "$PSScriptRoot/publish.js" @args; exit $LASTEXITCODE }
  }
}
if ($args.Count -gt 0 -and $args[0] -eq "env") {
  $roots = @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LOCALAPPDATA)
  $chrome = $roots | Where-Object { $_ } | ForEach-Object { Join-Path $_ 'Google/Chrome/Application/chrome.exe' } | Where-Object {Test-Path -LiteralPath $_}
  if (!$chrome) { Write-Output 'Chrome: https://www.google.cn/chrome/' } else { Write-Output "Chrome: $chrome" }
}
throw "Install Node.js LTS with npm, then continue."
