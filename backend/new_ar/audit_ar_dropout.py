"""Capture a bounded Test Localize replay for AR dropout diagnosis."""
import argparse
import collections
import json
from pathlib import Path

import requests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--video', required=True)
    parser.add_argument('--floor', required=True)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--destination-floor', required=True)
    parser.add_argument('--seconds', type=float, default=20)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    base = 'http://127.0.0.1:5000'
    current = requests.get(base + '/api/navigation-state', timeout=10).json()
    if current.get('active'):
        raise RuntimeError('An existing navigation session is active; leave it untouched.')
    response = requests.post(base + '/api/start-navigation', json={
        'video_filename': args.video, 'start_floor': args.floor,
        'destination': args.destination, 'destination_floor': args.destination_floor,
        'auto_floor': False, 'interval': 1.5,
    }, timeout=30)
    response.raise_for_status()
    sid = response.json()['session_id']
    args.output.parent.mkdir(parents=True, exist_ok=True)
    counts = collections.Counter()
    try:
        with args.output.open('w', encoding='utf-8') as output, requests.get(
            base + '/api/navigation-stream', params={'session_id': sid},
            stream=True, timeout=(10, 120),
        ) as stream:
            stream.raise_for_status()
            for line in stream.iter_lines(decode_unicode=True):
                if not line or not line.startswith('data:'):
                    continue
                event = json.loads(line[5:])
                output.write(json.dumps(event, ensure_ascii=False) + '\n')
                if event.get('type') == 'update':
                    counts['updates'] += 1
                    counts['ar_payload' if event.get('ar_world') else 'no_ar_payload'] += 1
                    counts[event.get('method', 'unknown')] += 1
                if float(event.get('timestamp', 0)) >= args.seconds:
                    break
                if event.get('type') == 'complete' or (
                    event.get('type') == 'error' and 'frame' not in event
                ):
                    break
    finally:
        requests.post(base + '/api/stop-navigation', json={'session_id': sid}, timeout=10).raise_for_status()
    print(json.dumps(dict(counts)))


if __name__ == '__main__':
    main()
