"""Mouse button tester for Windows (LMB, RMB, middle, side buttons, scroll wheel).

Uses a low-level mouse hook, so it sees every button the OS sees, including the
two side buttons (XBUTTON1 = Back, XBUTTON2 = Forward) that terminals normally
don't pass through. Clicks are NOT blocked; they still reach whatever is under
the cursor, so click on this terminal window while testing.

Run:  python mousetest.py      Quit: q / Esc (or Ctrl+C)
Keys: r = reset counters
"""

import ctypes
import msvcrt
import os
import sys
import threading
import time
from collections import deque
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WH_MOUSE_LL = 14
WM_QUIT = 0x0012
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0201, 0x0202
WM_RBUTTONDOWN, WM_RBUTTONUP = 0x0204, 0x0205
WM_MBUTTONDOWN, WM_MBUTTONUP = 0x0207, 0x0208
WM_MOUSEWHEEL = 0x020A
WM_XBUTTONDOWN, WM_XBUTTONUP = 0x020B, 0x020C
WM_MOUSEHWHEEL = 0x020E
XBUTTON1, XBUTTON2 = 1, 2
LLMHF_INJECTED = 0x01

LRESULT = ctypes.c_ssize_t


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE

BUTTONS = [("LMB", "Left"), ("RMB", "Right"), ("MMB", "Middle (wheel click)"),
           ("X1", "Side: Back (XButton1)"), ("X2", "Side: Forward (XButton2)")]

lock = threading.Lock()
state = {}


def reset():
    with lock:
        state.clear()
        state.update({
            "down": {k: False for k, _ in BUTTONS},
            "presses": {k: 0 for k, _ in BUTTONS},
            "releases": {k: 0 for k, _ in BUTTONS},
            "wheel_up": 0, "wheel_down": 0,
            "wheel_left": 0, "wheel_right": 0,
            "log": deque(maxlen=10),
            "t0": time.perf_counter(),
        })


def log(msg, injected=False):
    t = time.perf_counter() - state["t0"]
    state["log"].appendleft(f"{t:8.3f}s  {msg}" + ("  [injected/software]" if injected else ""))


def handle(wparam, info):
    hi = (info.mouseData >> 16) & 0xFFFF
    injected = bool(info.flags & LLMHF_INJECTED)
    btn, down = None, None
    if wparam in (WM_LBUTTONDOWN, WM_LBUTTONUP):
        btn, down = "LMB", wparam == WM_LBUTTONDOWN
    elif wparam in (WM_RBUTTONDOWN, WM_RBUTTONUP):
        btn, down = "RMB", wparam == WM_RBUTTONDOWN
    elif wparam in (WM_MBUTTONDOWN, WM_MBUTTONUP):
        btn, down = "MMB", wparam == WM_MBUTTONDOWN
    elif wparam in (WM_XBUTTONDOWN, WM_XBUTTONUP):
        btn = {XBUTTON1: "X1", XBUTTON2: "X2"}.get(hi, f"X?{hi}")
        down = wparam == WM_XBUTTONDOWN
    elif wparam in (WM_MOUSEWHEEL, WM_MOUSEHWHEEL):
        delta = hi - 0x10000 if hi & 0x8000 else hi
        if wparam == WM_MOUSEWHEEL:
            key = "wheel_up" if delta > 0 else "wheel_down"
            name = "Wheel UP" if delta > 0 else "Wheel DOWN"
        else:
            key = "wheel_right" if delta > 0 else "wheel_left"
            name = "Wheel RIGHT (tilt)" if delta > 0 else "Wheel LEFT (tilt)"
        state[key] += 1
        log(f"{name:<20} delta={delta:+d}", injected)
        return
    else:
        return  # mouse move etc.

    if btn not in state["down"]:
        log(f"Unknown button {btn} {'down' if down else 'up'}", injected)
        return
    state["down"][btn] = down
    state["presses" if down else "releases"][btn] += 1
    log(f"{btn:<4} {'DOWN' if down else 'up'}", injected)


@HOOKPROC
def hook_proc(ncode, wparam, lparam):
    if ncode == 0:
        info = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
        with lock:
            handle(wparam, info)
    return user32.CallNextHookEx(None, ncode, wparam, lparam)


hook_thread_id = None
hook_error = None


def hook_thread():
    global hook_thread_id, hook_error
    hook_thread_id = kernel32.GetCurrentThreadId()
    hook = user32.SetWindowsHookExW(WH_MOUSE_LL, hook_proc, kernel32.GetModuleHandleW(None), 0)
    if not hook:
        hook_error = ctypes.get_last_error()
        return
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        pass
    user32.UnhookWindowsHookEx(hook)


def render():
    with lock:
        lines = ["\x1b[H\x1b[1m Mouse Button Tester\x1b[0m   (q/Esc quit, r reset)\x1b[K", "\x1b[K"]
        lines.append(f"  {'Button':<26}{'State':<10}{'Presses':>8}{'Releases':>10}\x1b[K")
        lines.append("  " + "-" * 54 + "\x1b[K")
        for key, label in BUTTONS:
            down = state["down"][key]
            st = "\x1b[42;30m DOWN \x1b[0m   " if down else "\x1b[2m  up  \x1b[0m   "
            p = state["presses"][key]
            col = "\x1b[32m" if p else "\x1b[2m"
            lines.append(f"  {label:<26}{st} {col}{p:>8}\x1b[0m{state['releases'][key]:>10}\x1b[K")
        lines.append("\x1b[K")
        lines.append(f"  Scroll wheel    up: {state['wheel_up']:<6} down: {state['wheel_down']:<6}"
                     f"  (tilt L/R: {state['wheel_left']}/{state['wheel_right']})\x1b[K")
        lines.append("\x1b[K")
        lines.append("  \x1b[1mEvent log (newest first)\x1b[0m\x1b[K")
        log_lines = list(state["log"])
    lines += [f"  {l}\x1b[K" for l in log_lines]
    lines += ["\x1b[K"] * (10 - len(log_lines))
    sys.stdout.write("\n".join(lines) + "\x1b[J")
    sys.stdout.flush()


def main():
    if os.name != "nt":
        sys.exit("This tool is Windows-only.")
    os.system("")  # enable ANSI escape processing in the console
    reset()
    t = threading.Thread(target=hook_thread, daemon=True)
    t.start()
    time.sleep(0.2)
    if hook_error is not None:
        sys.exit(f"Failed to install mouse hook (error {hook_error}).")

    sys.stdout.write("\x1b[?25l\x1b[2J")  # hide cursor, clear screen
    try:
        while True:
            while msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("q", "Q", "\x1b"):
                    return
                if ch in ("r", "R"):
                    reset()
            render()
            time.sleep(0.03)
    except KeyboardInterrupt:
        pass
    finally:
        if hook_thread_id:
            user32.PostThreadMessageW(hook_thread_id, WM_QUIT, 0, 0)
        sys.stdout.write("\x1b[?25h\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
