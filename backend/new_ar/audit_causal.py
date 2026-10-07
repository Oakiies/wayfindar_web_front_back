"""Audit that a causal replay obeys live timing and report visible gaps."""
from pathlib import Path
import json

import argparse
parser=argparse.ArgumentParser()
parser.add_argument('--out',type=Path,default=Path(__file__).resolve().parent/'causal_0_60')
ROOT=parser.parse_args().out
poses=[json.loads(line) for line in (ROOT/'poses.jsonl').read_text().splitlines()]
render=json.loads((ROOT/'render_frames.json').read_text())
events=json.loads((ROOT/'calibration_events.json').read_text())

def gaps(rows,predicate):
    output=[];start=None
    for row in rows:
        missing=not predicate(row)
        if missing and start is None: start=row['time']
        if not missing and start is not None:
            output.append(dict(start_s=start,end_s=row['time'],duration_s=row['time']-start));start=None
    if start is not None:
        output.append(dict(start_s=start,end_s=rows[-1]['time'],duration_s=rows[-1]['time']-start))
    return sorted(output,key=lambda item:item['duration_s'],reverse=True)

checks={
    'backend_ready_before_camera': json.loads((ROOT/'backend_ready.json').read_text())['query_frames_consumed']==0,
    'all_seed_results_arrive_after_source': all(e['source_frame']<=e['available_frame'] for e in events['seed_events']),
    'all_seed_wall_times_after_source': all(e['source_time']<=e['available_wall_s'] for e in events['seed_events']),
    'all_calibration_evidence_is_past': all(max(e['evidence_frames'])<=e['available_at_frame'] for e in events['commits']),
    'all_rendered_frames_have_no_negative_latency': all(row['latency_s']>=0 for row in poses),
}
report=dict(checks=checks,all_pass=all(checks.values()),
    longest_pose_gaps=gaps(poses,lambda row:row['accepted'])[:8],
    longest_visible_ar_gaps=gaps(render,lambda row:row['visible_arrows']>0)[:8])
(ROOT/'causal_audit.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
if not report['all_pass']: raise SystemExit(1)
