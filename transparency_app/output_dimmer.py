"""Per-display output dimming through verified hardware gamma ramps.

This affects the final monitor output after Windows composes shell surfaces,
so Start and taskbars are included while screenshots retain framebuffer pixels.
Unsupported or silently rejected ramps return False so ScreenDimmer can use its
original overlay fallback instead.
"""

import ctypes
import ctypes.wintypes as wintypes
import json
import os


class GammaRamp(ctypes.Structure):
    _fields_ = [
        ("red", wintypes.WORD * 256),
        ("green", wintypes.WORD * 256),
        ("blue", wintypes.WORD * 256),
    ]


_CHANNELS = ("red", "green", "blue")
_VERIFY_TOLERANCE = 512
MAX_GAMMA_INTENSITY = 127  # keep output >= ~50%; darker ramps are rejected

gdi32 = ctypes.windll.gdi32
gdi32.CreateDCW.argtypes = [
    wintypes.LPCWSTR, wintypes.LPCWSTR,
    wintypes.LPCWSTR, ctypes.c_void_p]
gdi32.CreateDCW.restype = wintypes.HDC
gdi32.GetDeviceGammaRamp.argtypes = [wintypes.HDC, ctypes.c_void_p]
gdi32.GetDeviceGammaRamp.restype = wintypes.BOOL
gdi32.SetDeviceGammaRamp.argtypes = [wintypes.HDC, ctypes.c_void_p]
gdi32.SetDeviceGammaRamp.restype = wintypes.BOOL
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL


def _ramp_to_lists(ramp):
    return {name: [int(value) for value in getattr(ramp, name)]
            for name in _CHANNELS}


def _ramp_from_lists(values):
    if not isinstance(values, dict):
        return None
    ramp = GammaRamp()
    try:
        for name in _CHANNELS:
            channel = values[name]
            if not isinstance(channel, list) or len(channel) != 256:
                return None
            target = getattr(ramp, name)
            for index, value in enumerate(channel):
                target[index] = max(0, min(65535, int(value)))
    except (KeyError, TypeError, ValueError):
        return None
    return ramp


def _scaled_ramp(original, intensity):
    scale = (255 - max(0, min(200, int(intensity)))) / 255
    ramp = GammaRamp()
    for name in _CHANNELS:
        source = getattr(original, name)
        target = getattr(ramp, name)
        for index in range(256):
            target[index] = max(0, min(65535, round(source[index] * scale)))
    return ramp


def _ramps_match(expected, actual):
    for name in _CHANNELS:
        left = getattr(expected, name)
        right = getattr(actual, name)
        for index in range(256):
            if abs(int(left[index]) - int(right[index])) > _VERIFY_TOLERANCE:
                return False
    return True


class GammaDimmer:
    def __init__(self, ledger_path=None):
        self._ledger_path = ledger_path
        self._originals = {}
        self._recover()

    def _with_dc(self, device_name, operation):
        hdc = gdi32.CreateDCW("DISPLAY", str(device_name), None, None)
        if not hdc:
            return False
        try:
            return operation(hdc)
        finally:
            gdi32.DeleteDC(hdc)

    def _get(self, device_name):
        ramp = GammaRamp()
        ok = self._with_dc(
            device_name,
            lambda hdc: bool(gdi32.GetDeviceGammaRamp(
                hdc, ctypes.byref(ramp))))
        return ramp if ok else None

    def _set(self, device_name, ramp):
        return self._with_dc(
            device_name,
            lambda hdc: bool(gdi32.SetDeviceGammaRamp(
                hdc, ctypes.byref(ramp))))

    def apply(self, device_name, intensity):
        intensity = max(0, min(200, int(intensity)))
        if intensity <= 0:
            self.restore(device_name)
            return None
        applied_intensity = min(intensity, MAX_GAMMA_INTENSITY)
        name = str(device_name)
        original = self._originals.get(name)
        if original is None:
            original = self._get(name)
            if original is None:
                return False
            self._originals[name] = original
            self._write_ledger()
        target = _scaled_ramp(original, applied_intensity)
        if not self._set(name, target):
            self.restore(name)
            return None
        readback = self._get(name)
        if readback is None or not _ramps_match(target, readback):
            self.restore(name)
            return None
        return applied_intensity

    def restore(self, device_name):
        name = str(device_name)
        original = self._originals.pop(name, None)
        if original is not None:
            self._set(name, original)
            self._write_ledger()

    def restore_except(self, device_names):
        keep = {str(name) for name in device_names}
        for name in list(self._originals):
            if name not in keep:
                self.restore(name)

    def restore_all(self):
        for name in list(self._originals):
            self.restore(name)

    @property
    def active_devices(self):
        return set(self._originals)

    def _write_ledger(self):
        if not self._ledger_path:
            return
        try:
            if not self._originals:
                os.remove(self._ledger_path)
                return
            os.makedirs(os.path.dirname(self._ledger_path), exist_ok=True)
            data = {name: _ramp_to_lists(ramp)
                    for name, ramp in self._originals.items()}
            temporary = self._ledger_path + ".tmp"
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._ledger_path)
        except FileNotFoundError:
            pass
        except OSError:
            pass

    def _recover(self):
        if not self._ledger_path or not os.path.exists(self._ledger_path):
            return
        try:
            with open(self._ledger_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                for name, values in data.items():
                    ramp = _ramp_from_lists(values)
                    if ramp is not None:
                        self._set(name, ramp)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
        finally:
            try:
                os.remove(self._ledger_path)
            except OSError:
                pass
