"""macOS menu-bar app for the Switcher AC — a thin client of the local server.

Shows the room temperature (and a ❄ when the AC is on) in the menu bar, and a
dropdown to switch mode, flip the AC on/off, and open the dashboard. It reads
and writes the SAME backend as the web dashboard (http://localhost:3001), so
the two are always in sync — change the mode here and the webapp reflects it,
and vice-versa.

Run:   .venv/bin/python menubar.py     (needs `pip install rumps requests`)
Autostart is handled by the launchd agent — see daemon/.
"""

import webbrowser

import requests
import rumps

BASE = "http://localhost:3001"
TIMEOUT = 2.5           # keep the main thread responsive if the server is slow
REFRESH_SECONDS = 8

MODE_LABELS = {
    "manual": "Manual",
    "thermostat": "Thermostat (auto)",
    "cycle": "Cycle timer",
}


class ACMenuBar(rumps.App):
    def __init__(self):
        super().__init__("AC", title="AC …", quit_button="Quit")

        self.status_item = rumps.MenuItem("Loading…")
        self.detail_item = rumps.MenuItem("")

        # Mode submenu, one checkable item per mode.
        self.mode_items = {
            key: rumps.MenuItem(label, callback=self._make_set_mode(key))
            for key, label in MODE_LABELS.items()
        }
        mode_menu = rumps.MenuItem("Mode")
        for item in self.mode_items.values():
            mode_menu.add(item)

        # Target temperature submenu (the cool_temp setpoint used when the AC
        # turns on / cycles). One checkable item per °C across the valid range.
        self.temp_items = {
            t: rumps.MenuItem(f"{t}°C", callback=self._make_set_temp(t))
            for t in range(16, 31)
        }
        target_menu = rumps.MenuItem("Target temp")
        for item in self.temp_items.values():
            target_menu.add(item)

        self.on_item = rumps.MenuItem("Turn On", callback=self.turn_on)
        self.off_item = rumps.MenuItem("Turn Off", callback=self.turn_off)

        self.menu = [
            self.status_item,
            self.detail_item,
            None,
            mode_menu,
            target_menu,
            None,
            self.on_item,
            self.off_item,
            None,
            rumps.MenuItem("Open Dashboard", callback=self.open_dashboard),
            None,
        ]

        self._timer = rumps.Timer(self.refresh, REFRESH_SECONDS)
        self._timer.start()
        self.refresh(None)

    # ---- backend helpers ----
    def _get_state(self):
        try:
            return requests.get(f"{BASE}/api/state", timeout=TIMEOUT).json()
        except Exception:
            return None

    def _post_config(self, patch):
        try:
            requests.post(f"{BASE}/api/config", json=patch, timeout=TIMEOUT)
        except Exception:
            pass

    def _control(self, action, params=None):
        try:
            requests.get(f"{BASE}/control/{action}", params=params or {}, timeout=TIMEOUT + 5)
        except Exception:
            pass

    # ---- callbacks ----
    def _make_set_mode(self, key):
        def cb(_):
            self._post_config({"mode": key})
            self.refresh(None)
        return cb

    def _make_set_temp(self, temp):
        def cb(_):
            self._post_config({"cool_temp": temp})
            # If the AC is on right now, re-apply immediately so the new target
            # takes effect without waiting for the next loop tick.
            st = self._get_state() or {}
            if st.get("is_on"):
                self._control("on", {"temp": temp, "fan": "low", "mode": "cool"})
            self.refresh(None)
        return cb

    def turn_on(self, _):
        st = self._get_state() or {}
        cool = int(st.get("cool_temp", 26))
        self._control("on", {"temp": cool, "fan": "low", "mode": "cool"})
        self.refresh(None)

    def turn_off(self, _):
        self._control("off")
        self.refresh(None)

    def open_dashboard(self, _):
        webbrowser.open(BASE)

    # ---- periodic UI refresh ----
    def refresh(self, _):
        st = self._get_state()
        if st is None:
            self.title = "AC ⚠"
            self.status_item.title = "Server offline"
            self.detail_item.title = f"(no response from {BASE})"
            for item in self.mode_items.values():
                item.state = 0
            return

        temp = st.get("temperature")
        is_on = bool(st.get("is_on"))
        mode = st.get("mode", "manual")

        temp_str = f"{float(temp):.1f}°" if isinstance(temp, (int, float)) else "--°"
        self.title = f"{temp_str} ❄" if is_on else temp_str

        target = st.get("ac_temp")
        self.status_item.title = (
            f"AC ON · target {int(target)}°C" if (is_on and target is not None)
            else ("AC ON" if is_on else "AC OFF")
        )

        # Second line depends on the active mode.
        if mode == "cycle":
            phase = "Cooling" if st.get("cycle_phase") == "on" else "Idle"
            self.detail_item.title = (
                f"Cycle · {phase} · "
                f"{int(st.get('cycle_on_min', 5))}m on / {int(st.get('cycle_off_min', 25))}m off"
            )
        elif mode == "thermostat":
            self.detail_item.title = (
                f"Thermostat · {st.get('too_cold_temp')}–{st.get('too_hot_temp')}°C · "
                f"room {temp_str}"
            )
        else:
            self.detail_item.title = f"Manual · room {temp_str}"

        for key, item in self.mode_items.items():
            item.state = 1 if key == mode else 0

        cool = st.get("cool_temp")
        for t, item in self.temp_items.items():
            item.state = 1 if t == cool else 0


if __name__ == "__main__":
    ACMenuBar().run()
