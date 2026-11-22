"""Screenshots on GNOME Wayland via the xdg-desktop-portal Screenshot API."""
from __future__ import annotations

import secrets
import shutil
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

from .config import TMP_DIR


class ScreenshotError(RuntimeError):
    pass


def capture(interactive: bool = False, timeout: float = 90) -> Path:
    """Take a screenshot. interactive=True opens GNOME's picker so you can choose a region/window.

    The first time, GNOME asks whether Interview Gym may take screenshots; allow it once.
    """
    from jeepney import DBusAddress, MatchRule, new_method_call
    from jeepney.bus_messages import message_bus
    from jeepney.io.blocking import open_dbus_connection

    conn = open_dbus_connection(bus="SESSION")
    try:
        token = "alongside" + secrets.token_hex(4)
        sender = conn.unique_name[1:].replace(".", "_")
        handle = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        rule = MatchRule(type="signal", interface="org.freedesktop.portal.Request",
                         member="Response", path=handle)
        conn.send_and_get_reply(message_bus.AddMatch(rule))

        portal = DBusAddress("/org/freedesktop/portal/desktop",
                             bus_name="org.freedesktop.portal.Desktop",
                             interface="org.freedesktop.portal.Screenshot")
        options = {"handle_token": ("s", token), "interactive": ("b", interactive)}
        with conn.filter(rule) as q:
            conn.send_and_get_reply(new_method_call(portal, "Screenshot", "sa{sv}", ("", options)))
            signal = conn.recv_until_filtered(q, timeout=timeout)
        code, results = signal.body
        if code != 0:
            raise ScreenshotError("Screenshot was cancelled or not permitted.")
        uri = results["uri"][1]
    finally:
        conn.close()

    src = Path(unquote(urlparse(uri).path))
    dest = TMP_DIR / f"screen_{int(time.time() * 1000)}.png"
    try:
        shutil.move(src, dest)  # keep ~/Pictures clean
    except OSError:
        shutil.copy(src, dest)
    return dest


def cleanup(keep: int = 20) -> None:
    shots = sorted(TMP_DIR.glob("screen_*.png"))
    for p in shots[:-keep]:
        p.unlink(missing_ok=True)
