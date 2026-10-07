$ErrorActionPreference = 'Stop'
$arRoot = $PSScriptRoot
$arPython = Join-Path $arRoot '../.venv/Scripts/python.exe'
$arOutput = Join-Path $arRoot 'causal_0_60'

& $arPython (Join-Path $arRoot 'live_session.py') --out $arOutput
if ($LASTEXITCODE -ne 0) { throw 'Causal live simulation failed' }
& $arPython (Join-Path $arRoot 'render_live.py') --out $arOutput
if ($LASTEXITCODE -ne 0) { throw 'Causal render failed' }
& $arPython (Join-Path $arRoot 'audit_causal.py')
if ($LASTEXITCODE -ne 0) { throw 'Causal audit failed' }
& $arPython (Join-Path $arRoot 'test_world_ar.py')
if ($LASTEXITCODE -ne 0) { throw 'Geometry tests failed' }

Copy-Item -LiteralPath (Join-Path $arOutput 'IMG_1895_causal_AR.mp4') `
  -Destination (Join-Path $arRoot 'IMG_1895_AR_causal_0_60.mp4') -Force
