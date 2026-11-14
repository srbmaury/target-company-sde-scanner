"""Viewport frames and user input for a paused browser, on its Playwright thread."""

import base64
import math
import re
import secrets


KEYS = {"Tab", "Shift+Tab", "Enter", "Escape", "Backspace", "Delete", "Home", "End",
        "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "PageUp", "PageDown", "Space"}


def validate(body):
    if not isinstance(body, dict):
        raise ValueError("Invalid browser command.")
    action = body.get("action")
    if action in ("open", "frame", "release"):
        return {"action": action}
    out = {"action": action}
    if action in ("click", "scroll"):
        for key in ("x", "y"):
            val = body.get(key)
            if type(val) not in (int, float) or not 0 <= val <= 1:
                raise ValueError("Invalid browser position.")
            out[key] = val
        if action == "scroll":
            delta = body.get("delta")
            if type(delta) not in (int, float) or not -1600 <= delta <= 1600:
                raise ValueError("Invalid scroll amount.")
            out["delta"] = delta
    elif action == "text":
        val = body.get("text")
        if not isinstance(val, str) or not 1 <= len(val) <= 4000:
            raise ValueError("Enter up to 4000 characters.")
        out["text"] = val
    elif action == "key":
        val = body.get("key")
        if not isinstance(val, str) or (val not in KEYS and not re.fullmatch(r"[ -~]", val)):
            raise ValueError("Unsupported browser key.")
        out["key"] = val
    else:
        raise ValueError("Unknown browser command.")
    return out


def capture(page, *, quality=55):
    """Capture the actual viewport and mask password and OTP input elements."""
    masks = [frame.locator('input[type="password"], input[autocomplete="one-time-code"]') for frame in page.frames]
    return page.screenshot(type="jpeg", quality=quality, timeout=3500, animations="allow",
                           scale="css", full_page=False, mask=masks)


class Viewport:
    def __init__(self, page):
        self.page = page
        self.frame_id = None
        self.size = None

    def perform(self, command):
        page = self.page
        action = command["action"]
        if action not in ("open", "frame"):
            if not self.size:
                raise ValueError("The browser view is not ready.")
            width, height = self.size
            if action in ("click", "scroll"):
                x = min(width - 1, math.floor(width * command["x"]))
                y = min(height - 1, math.floor(height * command["y"]))
                if action == "click":
                    page.mouse.click(x, y, delay=45)
                else:
                    page.mouse.move(x, y)
                    page.mouse.wheel(0, command["delta"])
            elif action == "text":
                page.keyboard.insert_text(command["text"])
            elif action == "key":
                key = command["key"]
                page.keyboard.press(" " if key == "Space" else key)
            # The wheel and click can return before Chromium paints the new state.
            page.wait_for_timeout(32 if action == "scroll" else 180)
        frame = capture(page, quality=40 if action == "scroll" else 55)
        viewport = page.viewport_size
        self.size = (viewport["width"], viewport["height"]) if viewport else tuple(page.evaluate(
            "() => [window.innerWidth, window.innerHeight]"))
        self.frame_id = secrets.token_urlsafe(12)
        return {"image": base64.b64encode(frame).decode(), "frame_id": self.frame_id,
                "width": self.size[0], "height": self.size[1]}
