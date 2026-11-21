"""Process-wide settings that make the bot faster on every PC, applied by main.py before anything heavy is imported.

limit_blas_threads: numpy's OpenBLAS reserves ~24 MB of memory per hardware thread when numpy is imported (749 MB on a
32-thread CPU, measured 2026-11-16), for multi-threaded matrix products. Pyla only multiplies tiny matrices, which
OpenBLAS runs on one thread anyway. Must run before numpy is imported.

disable_power_throttling: Windows runs the threads of a process whose window is not in front as background work
(EcoQoS): efficiency cores and lowered clocks on hybrid Intel CPUs (12th gen and later), lowered clocks elsewhere. Pyla
always runs behind the emulator's window, so every frame paid for it. Opting out, measured on an i9-13900HX replaying a
match (2026-11-16): frame processing 14.9 -> 9.5 ms median, CPU time per frame 23.2 -> 17.7 ms, screen state checks
28 -> 16 ms. It also keeps Windows from ignoring the process's timer resolution while its windows are hidden.
PYLA_ALLOW_POWER_THROTTLING=1 keeps the Windows default (e.g. on battery).
"""
import os
import sys

# PROCESS_INFORMATION_CLASS ProcessPowerThrottling, PROCESS_POWER_THROTTLING_* (processthreadsapi.h)
_PROCESS_POWER_THROTTLING = 4
_THROTTLING_CURRENT_VERSION = 1
_THROTTLING_EXECUTION_SPEED = 0x1
_THROTTLING_IGNORE_TIMER_RESOLUTION = 0x4     # Windows 11 and later


def limit_blas_threads():
    """Cap numpy's BLAS threads (and the memory it reserves for them) unless the user set it."""
    for name in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(name, "1")


def disable_power_throttling():
    """Opt this process out of EcoQoS. True when Windows accepted it; False elsewhere or when not supported."""
    if sys.platform != "win32" or os.environ.get("PYLA_ALLOW_POWER_THROTTLING") == "1":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class PowerThrottlingState(ctypes.Structure):
            _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.SetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel32.SetProcessInformation.restype = wintypes.BOOL
        process = kernel32.GetCurrentProcess()
        # Windows 10 does not know the timer resolution flag and rejects the whole call: retry with execution speed.
        for control in (_THROTTLING_EXECUTION_SPEED | _THROTTLING_IGNORE_TIMER_RESOLUTION, _THROTTLING_EXECUTION_SPEED):
            # A flag in ControlMask but not in StateMask: that throttling is always off for this process.
            state = PowerThrottlingState(_THROTTLING_CURRENT_VERSION, control, 0)
            if kernel32.SetProcessInformation(process, _PROCESS_POWER_THROTTLING, ctypes.byref(state),
                                              ctypes.sizeof(state)):
                return True
    except (AttributeError, OSError):   # Windows 7 / 8: no SetProcessInformation or no power throttling class
        pass
    return False


def tune_process():
    limit_blas_threads()
    return disable_power_throttling()
