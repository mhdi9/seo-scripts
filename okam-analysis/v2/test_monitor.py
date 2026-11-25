"""Run: py -m unittest -v test_monitor.py"""
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from motorcycle_monitor import DEFAULTS, analyze, scan


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

    def test_recursive_scan_excludes_output(self):
        output = self.root / 'okam_analysis'
        output.mkdir()
        (output / 'ignored.mp4').touch()
        daily = self.root / '20261116'
        daily.mkdir()
        (daily / 'video.mp4').touch()
        self.assertEqual(list(scan(self.root, output.resolve())), [daily / 'video.mp4'])


if __name__ == '__main__':
    unittest.main()
