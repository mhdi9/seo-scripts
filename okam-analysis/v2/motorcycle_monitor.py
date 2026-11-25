"""Offline CCTV triage. Run: py motorcycle_monitor.py --help"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time

import cv2
import numpy as np
from openpyxl import Workbook

EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.h264', '.264', '.m4v', '.ts', '.dav'}
DEFAULTS = dict(sample_fps=8, min_area_ratio=0.0008, high_duration=0.5,
                event_gap=0.7, day_threshold=14, night_threshold=22,
                night_brightness=65, high_score=0.012, max_screenshots=8,
                sensitivity='high')


def save_json(path, data):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    temp.replace(path)


def scan(root, output):
    for directory, folders, files in os.walk(root):
        folders[:] = sorted(d for d in folders if Path(directory, d).resolve() != output)
        for name in sorted(files):
            path = Path(directory, name)
            if path.suffix.lower() in EXTENSIONS:
                yield path


def select_roi(video):
    cap = cv2.VideoCapture(str(video))
    try:
        ok, frame = cap.read()
        if not ok:
            raise ValueError('Representative video cannot be decoded')
    finally:
        cap.release()
    h, w = frame.shape[:2]
    scale = min(1, 1200 / w, 800 / h)
    preview = cv2.resize(frame, None, fx=scale, fy=scale)
    rect = cv2.selectROI('Include motorcycle AND surrounding approach area; ENTER confirms', preview, False)
    cv2.destroyAllWindows()
    x, y, rw, rh = [int(round(v / scale)) for v in rect]
    if rw < 5 or rh < 5:
        raise ValueError('ROI selection cancelled or too small')
    return dict(width=w, height=h, rectangle=[x, y, min(rw, w-x), min(rh, h-y)])


def decode_image(path, frame):
    ok, data = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 94])
    if not ok:
        raise IOError('Screenshot encoding failed')
    data.tofile(str(path))


def analyze(path, profile, cfg):
    cap = cv2.VideoCapture(str(path))
    events, active, previous, best_fallback = [], None, None, None
    model = cv2.createBackgroundSubtractorMOG2(history=400, varThreshold=25, detectShadows=False)
    frame_index = sampled = 0
    warnings = []
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        if not np.isfinite(fps) or fps <= 0:
            raise ValueError('Unknown frame rate; timing cannot be established safely')
        expected = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        step = max(1, int(fps / cfg['sample_fps']))
        interval = step / fps
        x, y, rw, rh = profile['rectangle']
        factor = {'low': 1.6, 'medium': 1.0, 'high': 0.7}[cfg['sensitivity']]
        while True:
            ok = cap.grab()
            if not ok:
                break
            frame_index += 1
            if (frame_index-1) % step:
                continue
            ok, frame = cap.retrieve()
            if not ok:
                warnings.append('Frame decode failure')
                continue
            if frame.shape[1] != profile['width'] or frame.shape[0] != profile['height']:
                raise ValueError('Resolution differs from selected camera profile; select/create correct profile')
            timestamp = (frame_index-1) / fps
            crop = frame[y:y+rh, x:x+rw]
            scale = min(1.0, 720 / max(rw, rh))
            gray = cv2.cvtColor(cv2.resize(crop, None, fx=scale, fy=scale), cv2.COLOR_BGR2GRAY)
            brightness = float(np.median(gray))
            night = brightness < cfg['night_brightness']
            gray = cv2.GaussianBlur(gray, (5, 5), 0)
            foreground = model.apply(gray, learningRate=0.004 if sampled > 10 else 0.03)
            sampled += 1
            if best_fallback is None:
                best_fallback = frame.copy()
            if previous is None:
                previous = gray
                continue
            # Remove uniform illumination shifts before testing local differences.
            delta = gray.astype(np.int16) - previous.astype(np.int16)
            shift = float(np.median(delta))
            difference = np.abs(delta-shift)
            threshold = cfg['night_threshold'] if night else cfg['day_threshold']
            mask = (difference > threshold * factor).astype(np.uint8)*255
            # Background subtraction supports slow movement after warm-up; frame
            # differences remain active from the second sample, including short clips.
            if sampled > 12:
                support = ((foreground > 0) & (difference > threshold*factor*0.5)).astype(np.uint8)*255
                mask = cv2.bitwise_or(mask, support)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            minimum = max(9, gray.size * cfg['min_area_ratio'] * factor)
            boxes, area = [], 0.0
            for contour in contours:
                a = cv2.contourArea(contour)
                if a >= minimum:
                    bx, by, bw, bh = cv2.boundingRect(contour)
                    boxes.append([x+int(bx/scale), y+int(by/scale), int(bw/scale), int(bh/scale)])
                    area += a
            score = area / gray.size
            uncertain = abs(shift) > 25 or float(np.mean(difference > threshold*factor)) > 0.65
            if boxes or uncertain:
                if active is None:
                    active = dict(start=max(0, timestamp-interval), end=timestamp, samples=0,
                                  score=0.0, uncertain=False, best=None, boxes=[], peak=timestamp)
                active['end'] = timestamp
                active['samples'] += 1
                active['uncertain'] |= uncertain
                if active['best'] is None or score > active['score']:
                    active.update(score=score, best=frame.copy(), boxes=boxes, peak=timestamp)
            elif active and timestamp-active['end'] > cfg['event_gap']:
                events.append(active)
                active = None
            previous = gray
        if active:
            events.append(active)
        if sampled == 0:
            raise ValueError('No readable frames; unsupported codec or corrupt file')
        if expected > 0 and frame_index < expected - max(2, fps*0.2):
            warnings.append('Video ended before advertised frame count; possibly truncated')
        if sampled < 3:
            warnings.append('Too few sampled frames for reliable analysis')
        high = any(e['samples'] >= 3 and e['end']-e['start'] >= cfg['high_duration']
                   and e['score'] >= cfg['high_score']*factor and not e['uncertain'] for e in events)
        category = 'HIGH_PRIORITY' if high else ('REVIEW' if events or warnings else 'NO_RELEVANT_MOTION')
        return category, events, warnings, best_fallback
    finally:
        cap.release()


def export_reports(db, output):
    headers = ['Date', 'Filename', 'Original Path', 'Classification', 'Motion Start', 'Motion End',
               'Motion Duration', 'Motion Score', 'Screenshot Path', 'Output Video Path',
               'Processing Status', 'Error Details', 'Events JSON', 'Camera Profile']
    report = output / 'reports'
    report.mkdir(exist_ok=True)
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet('Analysis')
    sheet.append(headers)
    temp = report / 'analysis_report.tmp.csv'
    with temp.open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        for (payload,) in db.execute('SELECT payload FROM results ORDER BY path'):
            row = json.loads(payload)
            values = [row.get(h, '') for h in headers]
            writer.writerow(values)
            # Force literal strings so filenames cannot become spreadsheet formulas.
            from openpyxl.cell import WriteOnlyCell
            cells = []
            for value in values:
                cell = WriteOnlyCell(sheet, value=value)
                if isinstance(value, str):
                    cell.data_type = 's'
                cells.append(cell)
            sheet.append(cells)
    temp.replace(report / 'analysis_report.csv')
    excel_temp = report / 'analysis_report.tmp.xlsx'
    workbook.save(excel_temp)
    excel_temp.replace(report / 'analysis_report.xlsx')


def main():
    parser = argparse.ArgumentParser(description='Offline motorcycle ROI motion review')
    parser.add_argument('--profile', default='camera1', help='Explicit camera profile; analyze one camera per run')
    parser.add_argument('--edit-roi', action='store_true')
    parser.add_argument('--retry-failed', action='store_true')
    parser.add_argument('--sensitivity', choices=['low', 'medium', 'high'])
    args = parser.parse_args()
    root = Path(input('Input video folder path: ').strip().strip('"')).expanduser().resolve()
    if not root.is_dir():
        raise ValueError('Input folder does not exist')
    output = root / 'okam_analysis'
    config_dir = output / 'config'
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / 'settings.json'
    cfg = {**DEFAULTS, **(json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else {})}
    if args.sensitivity:
        cfg['sensitivity'] = args.sensitivity
    if cfg['sample_fps'] <= 0 or cfg['max_screenshots'] < 1:
        raise ValueError('sample_fps and max_screenshots must be positive')
    save_json(config_path, cfg)
    roi_path = config_dir / 'roi_config.json'
    profiles = json.loads(roi_path.read_text(encoding='utf-8')) if roi_path.exists() else {}
    paths = list(scan(root, output.resolve()))
    paths.sort(key=lambda p: (str(p.relative_to(root).parent), p.name))
    if not paths:
        print('No supported videos found.')
        return
    print(f'{len(paths)} videos found. Camera profile: {args.profile}')
    print('Use only footage from this camera view in this run, even if other cameras share its resolution.')
    if args.edit_roi or args.profile not in profiles:
        representative = input('Representative video full path (Enter = first video): ').strip().strip('"')
        profiles[args.profile] = select_roi(Path(representative) if representative else paths[0])
        save_json(roi_path, profiles)
    profile = profiles[args.profile]
    signature = hashlib.sha256(json.dumps([cfg, profile, args.profile, 'v1'], sort_keys=True).encode()).hexdigest()
    db = sqlite3.connect(output / 'processing_state.sqlite3')
    db.execute('CREATE TABLE IF NOT EXISTS results(path TEXT PRIMARY KEY, fingerprint TEXT, payload TEXT)')
    counts = dict(HIGH_PRIORITY=0, REVIEW=0, NO_RELEVANT_MOTION=0, Failed=0, Skipped=0)
    try:
        for index, path in enumerate(paths, 1):
            stat = path.stat()
            fingerprint = f'{stat.st_size}:{stat.st_mtime_ns}:{signature}'
            prior = db.execute('SELECT fingerprint,payload FROM results WHERE path=?', (str(path),)).fetchone()
            if prior and prior[0] == fingerprint and not (args.retry_failed and json.loads(prior[1])['Processing Status'] == 'Failed'):
                counts['Skipped'] += 1
                print(f'[{index}/{len(paths)}] Already processed: {path.name}', flush=True)
                continue
            relative = path.relative_to(root)
            row = {'Date': relative.parts[0] if len(relative.parts)>1 else '', 'Filename': path.name,
                   'Original Path': str(path), 'Processing Status': 'Success', 'Camera Profile': args.profile}
            try:
                category, events, warnings, fallback = analyze(path, profile, cfg)
                row.update({'Classification': category, 'Error Details': '; '.join(warnings)})
                counts[category] += 1
                shots = []
                if category != 'NO_RELEVANT_MOTION':
                    destination = output / category / relative.parent
                    videos, screenshots = destination / 'videos', destination / 'screenshots'
                    videos.mkdir(parents=True, exist_ok=True)
                    screenshots.mkdir(parents=True, exist_ok=True)
                    # Stable, source-specific suffix also prevents collisions with screenshots.
                    tag = hashlib.sha256((str(relative)+signature+fingerprint).encode()).hexdigest()[:12]
                    target = videos / f'{path.stem}_{tag}{path.suffix}'
                    temporary = target.with_suffix(target.suffix+'.partial')
                    shutil.copy2(path, temporary)
                    temporary.replace(target)
                    row['Output Video Path'] = str(target)
                    chosen = sorted(events, key=lambda e: e['score'], reverse=True)[:int(cfg['max_screenshots'])]
                    if not chosen:
                        chosen = [dict(best=fallback, boxes=[], peak=0)]
                    for number, event in enumerate(chosen, 1):
                        image = event['best'].copy()
                        x, y, w, h = profile['rectangle']
                        cv2.rectangle(image, (x,y), (x+w,y+h), (0,255,255), 2)
                        for bx, by, bw, bh in event['boxes']:
                            cv2.rectangle(image, (bx,by), (bx+bw,by+bh), (0,0,255), 2)
                        stamp = f"{event['peak']:010.3f}".replace('.', '-')
                        shot = screenshots / f'{path.stem}_{tag}_event_{stamp}_{number}.jpg'
                        decode_image(shot, image)
                        shots.append(str(shot))
                metadata = [{k:v for k,v in e.items() if k not in {'best','boxes'}} for e in events]
                row.update({'Motion Start': min((e['start'] for e in events), default=''),
                            'Motion End': max((e['end'] for e in events), default=''),
                            'Motion Duration': sum(e['end']-e['start'] for e in events),
                            'Motion Score': max((e['score'] for e in events), default=0),
                            'Screenshot Path': '; '.join(shots), 'Events JSON': json.dumps(metadata)})
            except Exception as exc:
                row.update({'Processing Status': 'Failed', 'Classification': 'REVIEW', 'Error Details': str(exc)})
                counts['Failed'] += 1
            db.execute('INSERT OR REPLACE INTO results VALUES (?,?,?)', (str(path), fingerprint, json.dumps(row)))
            db.commit()
            print(f'[{index}/{len(paths)}; remaining {len(paths)-index}] {path.name}: '
                  f"{row.get('Classification')} / {row['Processing Status']} | {counts}", flush=True)
            if index % 100 == 0:
                export_reports(db, output)
    except KeyboardInterrupt:
        print('\nStopped. Run again with the same profile to resume; current video will be retried.')
    finally:
        try:
            export_reports(db, output)
        finally:
            db.close()
    print(f'Results: {output}')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'ERROR: {error}')
        raise SystemExit(1)
