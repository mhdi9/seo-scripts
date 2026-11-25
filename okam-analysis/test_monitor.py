"""Run: py -m unittest -v test_monitor.py"""
import tempfile
import unittest
import json
import sqlite3
import sys
import hashlib
from contextlib import closing
from unittest.mock import patch
from pathlib import Path

import cv2
import numpy as np

from motorcycle_monitor import DEFAULTS, analyze, scan, unavailable_reference, main


class SyntheticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.profile = dict(width=320, height=240, rectangle=[0, 0, 160, 240])

    def tearDown(self):
        self.temp.cleanup()

    def video(self, name, draw):
        path = self.root / name
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), 16, (320, 240))
        if not writer.isOpened():
            self.skipTest('MJPG encoder unavailable')
        try:
            for index in range(48):
                frame = np.full((240, 320, 3), 80, np.uint8)
                draw(frame, index)
                writer.write(frame)
        finally:
            writer.release()
        return path

    def test_static(self):
        path = self.video('static.avi', lambda f, i: None)
        self.assertEqual(analyze(path, self.profile, DEFAULTS)[0], 'NO_RELEVANT_MOTION')

    def test_outside_roi(self):
        path = self.video('outside.avi', lambda f, i: cv2.rectangle(f, (200+i, 80), (220+i, 130), (220,)*3, -1))
        self.assertEqual(analyze(path, self.profile, DEFAULTS)[0], 'NO_RELEVANT_MOTION')

    def test_inside_roi(self):
        path = self.video('inside.avi', lambda f, i: cv2.rectangle(f, (10+i*2, 80), (40+i*2, 130), (220,)*3, -1))
        category, events, _, _ = analyze(path, self.profile, DEFAULTS)
        self.assertEqual(category, 'HIGH_PRIORITY')
        self.assertTrue(events)

    def test_short_motion(self):
        def draw(frame, index):
            if 10 <= index <= 13:
                cv2.rectangle(frame, (40, 80), (80, 130), (220,)*3, -1)
        category = analyze(self.video('short.avi', draw), self.profile, DEFAULTS)[0]
        self.assertIn(category, {'REVIEW', 'HIGH_PRIORITY'})

    def test_dark_noise(self):
        rng = np.random.default_rng(42)
        def draw(frame, index):
            frame[:] = np.clip(30+rng.normal(0, 3, frame.shape), 0, 255).astype(np.uint8)
        self.assertEqual(analyze(self.video('noise.avi', draw), self.profile, DEFAULTS)[0], 'NO_RELEVANT_MOTION')

    def test_corrupt(self):
        path = self.root / 'broken.mp4'
        path.write_bytes(b'broken')
        with self.assertRaises(ValueError):
            analyze(path, self.profile, DEFAULTS)

    def test_exposure_flicker_on_textured_scene(self):
        rng = np.random.default_rng(1)
        texture = rng.integers(30, 160, (240, 320, 3), dtype=np.uint8)
        def draw(frame, index):
            frame[:] = np.clip(texture.astype(float)*(1 if index % 2 else 1.3)+index % 3*8, 0, 255).astype(np.uint8)
        self.assertEqual(analyze(self.video('flicker.avi', draw), self.profile, DEFAULTS)[0], 'NO_RELEVANT_MOTION')

    def test_known_unavailable_scene(self):
        def draw(frame, index):
            cv2.rectangle(frame, (50, 80), (150, 200), (230,)*3, -1)
        path = self.video('unavailable.avi', draw)
        profile = {**self.profile, 'unavailable_reference': unavailable_reference(path, self.profile)}
        self.assertEqual(analyze(path, profile, DEFAULTS)[0], 'UNASSESSABLE')

    def test_one_fps_real_motion_is_retained(self):
        path = self.root / 'lowfps.avi'
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), 1, (320,240))
        if not writer.isOpened():
            self.skipTest('MJPG encoder unavailable')
        for i in range(10):
            frame = np.full((240,320,3),80,np.uint8)
            cv2.rectangle(frame,(10+i*8,80),(40+i*8,130),(220,)*3,-1)
            writer.write(frame)
        writer.release()
        self.assertEqual(analyze(path,self.profile,DEFAULTS)[0], 'HIGH_PRIORITY')

    def test_recursive_scan_excludes_output(self):
        output = self.root / 'okam_analysis'
        output.mkdir()
        (output / 'ignored.mp4').touch()
        daily = self.root / '20261116'
        daily.mkdir()
        (daily / 'video.mp4').touch()
        self.assertEqual(list(scan(self.root, output.resolve())), [daily / 'video.mp4'])

    def test_reports_copy_screenshots_and_resume(self):
        path = self.video('activity.avi', lambda f, i: cv2.rectangle(f, (10+i*2,80),(40+i*2,130),(220,)*3,-1))
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        config = self.root / 'okam_analysis' / 'config'
        config.mkdir(parents=True)
        (config / 'roi_config.json').write_text(json.dumps({'camera1': self.profile}))
        with patch.object(sys, 'argv', ['monitor', '--input', str(self.root)]):
            main()
            main()
        output = self.root / 'okam_analysis' / 'v2'
        copies = list((output / 'HIGH_PRIORITY').rglob('*.avi'))
        self.assertEqual(len(copies), 1)
        self.assertEqual(hashlib.sha256(copies[0].read_bytes()).hexdigest(), before)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
        self.assertTrue(list(output.rglob('*.jpg')))
        self.assertTrue((output / 'reports' / 'analysis_report.xlsx').exists())
        with closing(sqlite3.connect(output / 'processing_state.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM results').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
