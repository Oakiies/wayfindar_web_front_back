# 1.5-second sampling experiment

This is an isolated experiment. The main Walkthrough replay remains on its
working PoC cadence of `0.05` seconds.

## Input

- Video: `navigate_indoor/uploads/floor5_2.mp4`
- Floor: `floor5`
- Destination: `Fire Exit 1`
- Sampling interval: `1.5` seconds (`90` frames at `59.94 FPS`)

## Outputs

- Video: `poc_interval_1p5_experiment.avi`
- Metrics: `poc_interval_1p5_experiment.csv`

The output was generated with:

```powershell
.\.venv\Scripts\python.exe poc_ar_arrow\render_poc.py --start 0 --end 4300 --step 90 --out poc_interval_1p5_experiment.avi --metrics poc_interval_1p5_experiment.csv
```

## Result

The 1.5-second run still produces the same AR logic, including turn cues. For
example, around `60.06s` the result is `TURN LEFT` with six visible v2 carets;
around `67.57s` it changes to `GO STRAIGHT` with two visible v2 carets.

Because this test updates only once every 1.5 seconds, the raw overlay moves in
steps. Making it visually smooth requires a separate interpolation experiment;
that behavior is intentionally not enabled in the main Walkthrough yet.
