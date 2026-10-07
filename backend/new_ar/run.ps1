$ErrorActionPreference = 'Stop'
$arPython = Join-Path $PSScriptRoot '../.venv/Scripts/python.exe'
foreach ($arStage in @('estimate_and_track.py', 'inspect_floor.py', 'render_video.py', 'check_ground_registration.py', 'package_results.py', 'visual_review.py')) {
    & $arPython (Join-Path $PSScriptRoot $arStage)
    if ($LASTEXITCODE -ne 0) { throw "Stage failed: $arStage" }
}
& $arPython (Join-Path $PSScriptRoot 'test_world_ar.py')
if ($LASTEXITCODE -ne 0) { throw 'Geometry tests failed' }
