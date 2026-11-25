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
                sensitivity='high', min_event_samples=2, noise_sigma=6.0,
                illumination_sigma=15, global_change_ratio=0.45,
                max_event_gap=0.35)

ALGORITHM_VERSION = 'v2_reflection_noise'


def motion_mask(previous, gray, cfg, threshold):
    """Compensate camera exposure, broad illumination and measured sensor noise.

    This does not recognize motorcycles or certify scene visibility.
    """
    previous = previous.astype(np.float32)
    current = gray.astype(np.float32)
    # Robust affine exposure fit using intensity percentiles; tolerate local objects.
    p = np.percentile(previous, [15, 85])
    q = np.percentile(current, [15, 85])
    gain = float(np.clip((q[1]-q[0])/max(10.0, p[1]-p[0]), 0.6, 1.7))
    delta = current - gain*previous
    offset = float(np.median(delta))
    residual = delta-offset
    broad = cv2.GaussianBlur(residual, (0, 0), cfg['illumination_sigma'])
    localized = residual-broad
    median = float(np.median(localized))
    noise = 1.4826*float(np.median(np.abs(localized-median)))
    cutoff = max(threshold, cfg['noise_sigma']*noise)
    raw = np.abs(localized) > cutoff
    global_change = float(np.mean(raw)) > cfg['global_change_ratio']
    mask = raw.astype(np.uint8)*255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    return mask, global_change


def boxes_related(first, second):
    # Require spatial continuity rather than adding unrelated noise across the ROI.
    return any(ax-12 <= bx+bw and bx-12 <= ax+aw and
               ay-12 <= by+bh and by-12 <= ay+ah
               for ax, ay, aw, ah in first for bx, by, bw, bh in second)


def scene_descriptor(frame):
    # Exclude timestamp band; compare the view, not the clock text.
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = gray[int(gray.shape[0]*0.12):]
    return cv2.resize(gray, (160, 90), interpolation=cv2.INTER_AREA).astype(np.float32)


def unavailable_match(frame, reference):
    current = scene_descriptor(frame)
    reference = np.asarray(reference, np.float32)
    if reference.shape != current.shape:
        return False
    # Permit small exposure offsets; do not equate arbitrary dark images.
    difference = current-reference
    difference -= np.median(difference)
    if np.std(current) < 5 or np.std(reference) < 5:
        return False
    correlation = np.corrcoef(current.ravel(), reference.ravel())[0, 1]
    return correlation > 0.98 and np.percentile(np.abs(difference), 95) < 12


def unavailable_reference(video, profile):
    cap = cv2.VideoCapture(str(video))
    try:
        ok, frame = cap.read()
        if not ok:
            raise ValueError('Cannot read unavailable-view reference video')
        if frame.shape[:2] != (profile['height'], profile['width']):
            raise ValueError('Unavailable reference resolution differs from camera profile')
        return scene_descriptor(frame).tolist()
    finally:
        cap.release()


def save_json(path, data):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    temp.replace(path)


def scan(root, output):
    for directory, folders, files in os.walk(root):
        folders[:] = sorted(d for d in folders
                            if d.casefold() != 'okam_analysis'
                            and Path(directory, d).resolve() != output)
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
    cfg = {**DEFAULTS, **cfg}
    cap = cv2.VideoCapture(str(path))
    events, active, previous, best_fallback = [], None, None, None
    frame_index = sampled = 0
    unavailable_frames = 0
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
            sampled += 1
            if 'unavailable_reference' in profile and unavailable_match(frame, profile['unavailable_reference']):
                unavailable_frames += 1
            if best_fallback is None:
                best_fallback = frame.copy()
            if previous is None:
                previous = gray
                continue
            threshold = cfg['night_threshold'] if night else cfg['day_threshold']
            mask, global_change = motion_mask(previous, gray, cfg, threshold*factor)
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
            # Illumination alone never creates an event. Widespread residual
            # motion remains REVIEW, never HIGH_PRIORITY.
            uncertain = global_change
            if active and (timestamp-active['end'] > max(cfg['max_event_gap'], interval*1.5) or
                           (boxes and not boxes_related(active['last_boxes'], boxes))):
                events.append(active)
                active = None
            if boxes:
                if active is None:
                    active = dict(start=max(0, timestamp-interval), end=timestamp, samples=0,
                                  score=0.0, uncertain=False, best=None, boxes=[], peak=timestamp,
                                  last_boxes=boxes)
                active['end'] = timestamp
                active['samples'] += 1
                active['uncertain'] |= uncertain
                active['last_boxes'] = boxes
                if active['best'] is None or score > active['score']:
                    active.update(score=score, best=frame.copy(), boxes=boxes, peak=timestamp)
            elif active and timestamp-active['end'] > cfg['event_gap']:
                events.append(active)
                active = None
            previous = gray
        if active:
            events.append(active)
        # A single isolated frame is not sufficient evidence. Keep short,
        # spatially related events for REVIEW, without upgrading them to HIGH.
        events = [e for e in events if e['samples'] >= cfg['min_event_samples']]
        if sampled == 0:
            raise ValueError('No readable frames; unsupported codec or corrupt file')
        if expected > 0 and frame_index < expected - max(2, fps*0.2):
            warnings.append('Video ended before advertised frame count; possibly truncated')
        if sampled < 3:
            warnings.append('Too few sampled frames for reliable analysis')
        high = any(e['samples'] >= 3 and e['end']-e['start'] >= cfg['high_duration']
                   and e['score'] >= cfg['high_score']*factor and not e['uncertain'] for e in events)
        category = 'HIGH_PRIORITY' if high else ('REVIEW' if events or warnings else 'NO_RELEVANT_MOTION')
        if unavailable_frames / sampled >= 0.95:
            category = 'UNASSESSABLE'
            warnings.append('View matches manually designated unavailable scene in >=95% of samples; motorcycle visibility cannot be assessed')
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
    parser.add_argument('--input', help='Optional input folder; otherwise asked in terminal')
    parser.add_argument('--unavailable-reference', help='Video showing a known reflection-obscured view; report matching clips without copying')
    parser.add_argument('--clear-unavailable-reference', action='store_true')
    args = parser.parse_args()
    root = Path((args.input or input('Input video folder path: ')).strip().strip('"')).expanduser().resolve()
    if not root.is_dir():
        raise ValueError('Input folder does not exist')
    output_root = root / 'okam_analysis'
    output = output_root / 'v2'
    output.mkdir(parents=True, exist_ok=True)
    print(f'Active program: {Path(__file__).resolve()}')
    print(f'Current results folder: {output}')
    print('Old results outside this folder are from earlier runs; all okam_analysis folders are excluded.')
    config_dir = output_root / 'config'
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
    paths = list(scan(root, output_root.resolve()))
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
    if args.clear_unavailable_reference:
        profile.pop('unavailable_reference', None)
    if args.unavailable_reference:
        profile['unavailable_reference'] = unavailable_reference(Path(args.unavailable_reference), profile)
    save_json(roi_path, profiles)
    signature = hashlib.sha256(json.dumps([cfg, profile, args.profile, ALGORITHM_VERSION], sort_keys=True).encode()).hexdigest()
    db = sqlite3.connect(output / 'processing_state.sqlite3')
    db.execute('CREATE TABLE IF NOT EXISTS results(path TEXT PRIMARY KEY, fingerprint TEXT, payload TEXT)')
    counts = dict(HIGH_PRIORITY=0, REVIEW=0, NO_RELEVANT_MOTION=0, UNASSESSABLE=0, Failed=0, Skipped=0)
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
                if category in {'HIGH_PRIORITY', 'REVIEW'}:
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
                metadata = [{k:v for k,v in e.items() if k not in {'best','boxes','last_boxes'}} for e in events]
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
