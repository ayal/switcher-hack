"""Native macOS menu-bar widget for the Switcher AC.

An NSStatusItem showing the room temp (+ ❄ when on), whose click opens a native
NSPopover built from real AppKit controls — a power button, a Manual/Auto/Cycle
segmented control, a target-temperature slider, and (in cycle mode) on/off
steppers with a live phase countdown. No HTML: this is genuine AppKit, the same
control family as macOS Control Center.

It's a thin client of the local server (http://127.0.0.1:3001), so it stays in
sync with the web dashboard — change something here and the dashboard reflects
it, and vice-versa.

Run:   .venv/bin/python menubar.py      (needs pyobjc + requests)
Autostart is handled by the launchd agent — see daemon/.
"""

import json
import threading
import time
import webbrowser
from datetime import datetime

import objc
import requests

from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBezelStyleRounded,
    NSColor,
    NSFont,
    NSPopover,
    NSPopoverBehaviorTransient,
    NSSegmentedControl,
    NSSegmentStyleRounded,
    NSSegmentSwitchTrackingSelectOne,
    NSSlider,
    NSStatusBar,
    NSStepper,
    NSTextAlignmentRight,
    NSTextField,
    NSVariableStatusItemLength,
    NSView,
    NSViewController,
    NSButton,
)
from Foundation import NSMakeRect, NSObject
from PyObjCTools import AppHelper

try:
    from AppKit import NSMinYEdge as _EDGE
except Exception:  # pragma: no cover - constant name fallback
    _EDGE = 1

API = "http://127.0.0.1:3001"
W = 300           # popover width
P = 16            # padding
MANUAL_H = 250    # popover height for manual/thermostat
CYCLE_H = 340     # popover height for cycle mode
MODE_ORDER = ["manual", "thermostat", "cycle"]
MODE_INDEX = {m: i for i, m in enumerate(MODE_ORDER)}


class FlippedView(NSView):
    """Top-left origin so we can lay out with y growing downward."""
    def isFlipped(self):
        return True


def _safe(fn):
    try:
        fn()
    except Exception:
        pass


def _countdown(iso):
    if not iso:
        return "—"
    try:
        rem = max(0, int((datetime.fromisoformat(iso) - datetime.now()).total_seconds()))
    except Exception:
        return "—"
    m, s = divmod(rem, 60)
    return "%d:%02d" % (m, s) if m else "%ds" % s


def _label(frame, text, size=13, bold=False, secondary=False, right=False):
    f = NSTextField.alloc().initWithFrame_(NSMakeRect(*frame))
    f.setStringValue_(text)
    f.setBezeled_(False)
    f.setDrawsBackground_(False)
    f.setEditable_(False)
    f.setSelectable_(False)
    f.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
    if secondary:
        f.setTextColor_(NSColor.secondaryLabelColor())
    if right:
        f.setAlignment_(NSTextAlignmentRight)
    return f


class ACDelegate(NSObject):
    def applicationDidFinishLaunching_(self, notification):
        self._is_on = False
        self._cur_mode = None

        # --- status-bar item ---
        self.statusItem = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength)
        btn = self.statusItem.button()
        btn.setTitle_("AC …")
        btn.setTarget_(self)
        btn.setAction_("statusClicked:")

        # --- popover + root view ---
        self.root = FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, W, MANUAL_H))
        self._build_controls()

        vc = NSViewController.alloc().init()
        vc.setView_(self.root)
        self.popover = NSPopover.alloc().init()
        self.popover.setContentViewController_(vc)
        self.popover.setBehavior_(NSPopoverBehaviorTransient)
        self.popover.setAnimates_(True)
        self.popover.setContentSize_((W, MANUAL_H))

        # --- periodic refresh ---
        self.refresh_(None)
        AppHelper.callLater(0.1, self._start_timer)

    @objc.python_method
    def _start_timer(self):
        from Foundation import NSTimer
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            6.0, self, "refresh:", None, True)

    # ------------------------------------------------------------------ build
    @objc.python_method
    def _build_controls(self):
        r = self.root
        self.titleLabel = _label((P, 12, 150, 20), "AYAL AC", size=15, bold=True)
        r.addSubview_(self.titleLabel)
        self.tempLabel = _label((W - 120 - P, 8, 120, 28), "--°", size=22, bold=True, right=True)
        r.addSubview_(self.tempLabel)

        self.powerBtn = NSButton.alloc().initWithFrame_(NSMakeRect(P, 44, W - 2 * P, 40))
        self.powerBtn.setBezelStyle_(NSBezelStyleRounded)
        self.powerBtn.setTitle_("Turn On")
        self.powerBtn.setTarget_(self)
        self.powerBtn.setAction_("powerClicked:")
        r.addSubview_(self.powerBtn)

        self.statusLabel = _label((P, 88, W - 2 * P, 16), "…", size=11, secondary=True)
        r.addSubview_(self.statusLabel)

        self.modeSeg = NSSegmentedControl.alloc().initWithFrame_(NSMakeRect(P, 110, W - 2 * P, 26))
        self.modeSeg.setSegmentStyle_(NSSegmentStyleRounded)
        self.modeSeg.setSegmentCount_(3)
        self.modeSeg.setTrackingMode_(NSSegmentSwitchTrackingSelectOne)
        for i, lbl in enumerate(["Manual", "Auto", "Cycle"]):
            self.modeSeg.setLabel_forSegment_(lbl, i)
        self.modeSeg.setTarget_(self)
        self.modeSeg.setAction_("modeChanged:")
        r.addSubview_(self.modeSeg)

        r.addSubview_(_label((P, 148, 80, 16), "Target", size=12, secondary=True))
        self.targetValue = _label((W - 80 - P, 148, 80, 16), "--°C", size=12, bold=True, right=True)
        r.addSubview_(self.targetValue)
        self.targetSlider = NSSlider.alloc().initWithFrame_(NSMakeRect(P, 168, W - 2 * P, 24))
        self.targetSlider.setMinValue_(16)
        self.targetSlider.setMaxValue_(30)
        self.targetSlider.setNumberOfTickMarks_(15)
        self.targetSlider.setAllowsTickMarkValuesOnly_(True)
        self.targetSlider.setContinuous_(True)
        self.targetSlider.setTarget_(self)
        self.targetSlider.setAction_("targetChanged:")
        r.addSubview_(self.targetSlider)

        # --- cycle-only controls (hidden unless mode == cycle) ---
        self.cycleStatus = _label((P, 204, W - 2 * P, 16), "", size=12, secondary=True)
        r.addSubview_(self.cycleStatus)
        r.addSubview_(self._cycle_row_label((P, 230), "On"))
        self.onValue = _label((P + 34, 230, 44, 18), "5m", size=12, bold=True)
        r.addSubview_(self.onValue)
        self.onStepper = self._stepper((P + 80, 226), "onStepperChanged:")
        r.addSubview_(self.onStepper)
        r.addSubview_(self._cycle_row_label((P + 130, 230), "Off"))
        self.offValue = _label((P + 168, 230, 44, 18), "25m", size=12, bold=True)
        r.addSubview_(self.offValue)
        self.offStepper = self._stepper((W - P - 19, 226), "offStepperChanged:")
        r.addSubview_(self.offStepper)
        self.cycleControls = [self.cycleStatus, self.onValue, self.onStepper,
                              self.offValue, self.offStepper]
        # self._cycle_static holds the "On"/"Off" text labels (populated by
        # _cycle_row_label above); they hide/show with the rest of cycle mode.

        # --- footer ---
        self.dashBtn = NSButton.alloc().initWithFrame_(NSMakeRect(P, MANUAL_H - 34, 130, 24))
        self.dashBtn.setBezelStyle_(NSBezelStyleRounded)
        self.dashBtn.setTitle_("Dashboard")
        self.dashBtn.setTarget_(self)
        self.dashBtn.setAction_("openDashboard:")
        r.addSubview_(self.dashBtn)
        self.quitBtn = NSButton.alloc().initWithFrame_(NSMakeRect(W - P - 84, MANUAL_H - 34, 84, 24))
        self.quitBtn.setBezelStyle_(NSBezelStyleRounded)
        self.quitBtn.setTitle_("Quit")
        self.quitBtn.setTarget_(self)
        self.quitBtn.setAction_("quitClicked:")
        r.addSubview_(self.quitBtn)

        self._last_user_target = 0.0

    @objc.python_method
    def _cycle_row_label(self, origin, text):
        lbl = _label((origin[0], origin[1], 30, 18), text, size=12, secondary=True)
        # remember these so they hide/show with the rest of the cycle controls
        if not hasattr(self, "_cycle_static"):
            self._cycle_static = []
        self._cycle_static.append(lbl)
        return lbl

    @objc.python_method
    def _stepper(self, origin, action):
        st = NSStepper.alloc().initWithFrame_(NSMakeRect(origin[0], origin[1], 19, 27))
        st.setMinValue_(1)
        st.setMaxValue_(240)
        st.setIncrement_(1)
        st.setValueWraps_(False)
        st.setTarget_(self)
        st.setAction_(action)
        return st

    # ------------------------------------------------------------- networking
    @objc.python_method
    def _bg(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    @objc.python_method
    def _post_config(self, patch):
        self._bg(lambda: _safe(lambda: requests.post(API + "/api/config", json=patch, timeout=3)))

    @objc.python_method
    def _control(self, action, params=None):
        self._bg(lambda: _safe(lambda: requests.get(API + "/control/" + action, params=params or {}, timeout=8)))

    # ------------------------------------------------------------- UI actions
    def statusClicked_(self, sender):
        if self.popover.isShown():
            self.popover.performClose_(sender)
        else:
            btn = self.statusItem.button()
            self.popover.showRelativeToRect_ofView_preferredEdge_(btn.bounds(), btn, _EDGE)
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            self.refresh_(None)

    def powerClicked_(self, sender):
        if self._is_on:
            self._control("off")
        else:
            v = int(round(self.targetSlider.doubleValue())) or 26
            self._control("on", {"temp": v, "fan": "low", "mode": "cool"})
        self.performSelector_withObject_afterDelay_("refresh:", None, 1.3)

    def modeChanged_(self, sender):
        m = MODE_ORDER[sender.selectedSegment()]
        self._cur_mode = m
        self._apply_mode(m)
        self._post_config({"mode": m})
        self.performSelector_withObject_afterDelay_("refresh:", None, 1.0)

    def targetChanged_(self, sender):
        v = int(round(sender.doubleValue()))
        self.targetValue.setStringValue_("%d°C" % v)
        self._last_user_target = time.time()
        NSObject.cancelPreviousPerformRequestsWithTarget_selector_object_(self, "commitTarget:", None)
        self.performSelector_withObject_afterDelay_("commitTarget:", None, 0.4)

    def commitTarget_(self, _):
        v = int(round(self.targetSlider.doubleValue()))
        self._post_config({"cool_temp": v})
        self._bg(lambda: self._reapply_if_on(v))

    @objc.python_method
    def _reapply_if_on(self, v):
        try:
            st = requests.get(API + "/api/state", timeout=2).json()
            if st.get("is_on"):
                requests.get(API + "/control/on",
                             params={"temp": v, "fan": "low", "mode": "cool"}, timeout=8)
        except Exception:
            pass

    def onStepperChanged_(self, sender):
        v = int(sender.doubleValue())
        self.onValue.setStringValue_("%dm" % v)
        self._post_config({"cycle_on_min": v})

    def offStepperChanged_(self, sender):
        v = int(sender.doubleValue())
        self.offValue.setStringValue_("%dm" % v)
        self._post_config({"cycle_off_min": v})

    def openDashboard_(self, sender):
        webbrowser.open(API)

    def quitClicked_(self, sender):
        NSApplication.sharedApplication().terminate_(self)

    # ------------------------------------------------------------- refresh
    def refresh_(self, _timer):
        self._bg(self._poll)

    @objc.python_method
    def _poll(self):
        try:
            s = requests.get(API + "/api/state", timeout=2).text
        except Exception:
            s = ""
        self.performSelectorOnMainThread_withObject_waitUntilDone_("applyState:", s, False)

    @objc.python_method
    def _apply_mode(self, mode):
        """Show/hide cycle controls and resize the popover to fit."""
        is_cycle = mode == "cycle"
        for c in self.cycleControls + getattr(self, "_cycle_static", []):
            c.setHidden_(not is_cycle)
        h = CYCLE_H if is_cycle else MANUAL_H
        self.root.setFrameSize_((W, h))
        self.popover.setContentSize_((W, h))
        fy = h - 34
        self.dashBtn.setFrameOrigin_((P, fy))
        self.quitBtn.setFrameOrigin_((W - P - 84, fy))

    def applyState_(self, s):
        try:
            st = json.loads(str(s)) if s else None
        except Exception:
            st = None

        if st is None:
            self.statusItem.button().setTitle_("AC ⚠")
            self.statusLabel.setStringValue_("Server offline")
            return

        temp = st.get("temperature")
        self._is_on = bool(st.get("is_on"))
        mode = st.get("mode", "manual")
        temp_str = "%.1f°" % float(temp) if isinstance(temp, (int, float)) else "--°"

        # menu-bar title
        self.statusItem.button().setTitle_(temp_str + " ❄" if self._is_on else temp_str)
        self.tempLabel.setStringValue_(temp_str)

        # power + status line
        self.powerBtn.setTitle_("Turn Off" if self._is_on else "Turn On")
        target = st.get("ac_temp")
        if self._is_on and target is not None:
            self.statusLabel.setStringValue_("AC ON · target %d°C" % int(target))
        else:
            self.statusLabel.setStringValue_("AC OFF")

        # mode + layout
        self.modeSeg.setSelectedSegment_(MODE_INDEX.get(mode, 0))
        if mode != self._cur_mode:
            self._cur_mode = mode
            self._apply_mode(mode)

        # inputs: only sync when the popover is closed (don't fight the user),
        # except a short grace window after the user last moved the slider
        can_sync_inputs = (not self.popover.isShown()) or (time.time() - self._last_user_target > 3)
        cool = st.get("cool_temp")
        if can_sync_inputs and isinstance(cool, (int, float)):
            self.targetSlider.setDoubleValue_(float(cool))
            self.targetValue.setStringValue_("%d°C" % int(cool))

        if mode == "cycle":
            phase = "Cooling" if st.get("cycle_phase") == "on" else "Idle"
            self.cycleStatus.setStringValue_(
                "Cycle · %s · switches in %s" % (phase, _countdown(st.get("cycle_phase_until"))))
            on_m = int(st.get("cycle_on_min", 5))
            off_m = int(st.get("cycle_off_min", 25))
            self.onValue.setStringValue_("%dm" % on_m)
            self.offValue.setStringValue_("%dm" % off_m)
            if not self.popover.isShown():
                self.onStepper.setDoubleValue_(on_m)
                self.offStepper.setDoubleValue_(off_m)


if __name__ == "__main__":
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    delegate = ACDelegate.alloc().init()
    app.setDelegate_(delegate)
    AppHelper.runEventLoop()
