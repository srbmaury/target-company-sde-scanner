"""Hosted browser commands run only on the worker that owns Playwright."""

import queue
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from jobbot.ui.bridge import ApplyRun, WebUI
from jobbot.ui.live_preview import validate


class LivePreviewTests(unittest.TestCase):
    def start_preview(self, *, dry=False):
        run = ApplyRun(SimpleNamespace(owner="fixture"))
        run.dry_run = dry
        page = Mock(viewport_size={"width": 1000, "height": 600}, frames=[Mock()])
        result = queue.Queue()
        owner = []

        def snapshot(**options):
            self.assertEqual(threading.get_ident(), owner[0])
            self.assertEqual(options["mask"], [page.frames[0].locator.return_value])
            return b"jpeg"

        page.screenshot.side_effect = snapshot

        def pause():
            owner.append(threading.get_ident())
            result.put(WebUI(run).next_action(not dry, False, dry, page=page))

        worker = threading.Thread(target=pause, daemon=True)
        worker.start()
        self.addCleanup(worker.join, 2)
        self.addCleanup(run.stop)
        for _ in range(100):
            if run.prompt:
                break
            time.sleep(.01)
        self.assertTrue(run.prompt["interactive"])
        prompt = run.prompt["id"]
        first = run.control({"action": "open", "prompt_id": prompt})
        self.assertEqual((first["width"], first["height"]), (1000, 600))
        self.assertEqual(first["image"], "anBlZw==")
        return run, page, result, {"prompt_id": prompt, "control": first["control"], "frame_id": first["frame_id"]}

    def test_takeover_routes_input_and_invalidates_previous_submit_prompt(self):
        run, page, result, auth = self.start_preview()
        with self.assertRaisesRegex(ValueError, "Another tab"):
            run.control({"action": "open", "prompt_id": auth["prompt_id"]})
        with self.assertRaisesRegex(ValueError, "Return control"):
            run.answer(auth["prompt_id"], "submit")
        reply = run.control({**auth, "action": "click", "x": .25, "y": .5})
        page.mouse.click.assert_called_once_with(250, 300, delay=45)
        with self.assertRaisesRegex(ValueError, "view changed"):
            run.control({**auth, "action": "text", "text": "Bengaluru"})
        run.control({**auth, "frame_id": reply["frame_id"], "action": "text", "text": "Bengaluru"})
        page.keyboard.insert_text.assert_called_once_with("Bengaluru")
        run.control({**auth, "action": "release"})
        self.assertEqual(result.get(timeout=2), "recheck")
        with self.assertRaises(ValueError):
            run.answer(auth["prompt_id"], "submit")

    def test_scroll_keyboard_refresh_and_recovery(self):
        run, page, result, auth = self.start_preview()
        reply = run.control({**auth, "action": "scroll", "x": .5, "y": .25, "delta": 360})
        page.mouse.move.assert_called_once_with(500, 150)
        page.mouse.wheel.assert_called_once_with(0, 360)
        auth["frame_id"] = reply["frame_id"]
        original = page.screenshot.side_effect
        page.screenshot.side_effect = RuntimeError("frame capture failed")
        with self.assertRaisesRegex(ValueError, "Refresh"):
            run.control({**auth, "action": "key", "key": "Tab"})
        page.keyboard.press.assert_called_once_with("Tab")
        page.screenshot.side_effect = original
        run.control({**auth, "action": "frame"})
        run.control({**auth, "action": "release"})
        self.assertEqual(result.get(timeout=2), "recheck")

    def test_dry_run_allows_frames_but_no_remote_input(self):
        run, page, result, auth = self.start_preview(dry=True)
        with self.assertRaisesRegex(ValueError, "read-only"):
            run.control({**auth, "action": "click", "x": 1, "y": 1})
        page.mouse.click.assert_not_called()
        run.control({**auth, "action": "release"})
        with self.assertRaisesRegex(ValueError, "not available"):
            run.answer(auth["prompt_id"], "submit")
        run.answer(auth["prompt_id"], "quit")
        self.assertEqual(result.get(timeout=2), "quit")

    def test_only_bounded_browser_inputs_are_accepted(self):
        for data in ({"action": "navigate", "url": "https://example.com"},
                     {"action": "click", "x": -1, "y": 0},
                     {"action": "scroll", "x": 0, "y": 0, "delta": float("nan")},
                     {"action": "key", "key": "Control+l"},
                     {"action": "text", "text": "a" * 4001}):
            with self.subTest(data=data["action"]), self.assertRaises(ValueError):
                validate(data)
