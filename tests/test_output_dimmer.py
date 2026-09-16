import json

from transparency_app.output_dimmer import GammaDimmer, GammaRamp


def identity_ramp():
    ramp = GammaRamp()
    for name in ("red", "green", "blue"):
        channel = getattr(ramp, name)
        for index in range(256):
            channel[index] = index * 257
    return ramp


def clone_ramp(source):
    target = GammaRamp()
    for name in ("red", "green", "blue"):
        left = getattr(source, name)
        right = getattr(target, name)
        for index in range(256):
            right[index] = left[index]
    return target


def fake_driver(dimmer, original):
    current = {"DISPLAY1": clone_ramp(original)}

    def get(name):
        return clone_ramp(current.get(name, original))

    def set_ramp(name, ramp):
        current[name] = clone_ramp(ramp)
        return True

    dimmer._get = get
    dimmer._set = set_ramp
    return current


def test_verified_gamma_apply_scales_and_restores_exactly(tmp_path):
    ledger = tmp_path / "gamma-session.json"
    original = identity_ramp()
    dimmer = GammaDimmer(str(ledger))
    current = fake_driver(dimmer, original)

    assert dimmer.apply("DISPLAY1", 111) == 111
    assert current["DISPLAY1"].red[255] == round(65535 * (144 / 255))
    assert dimmer.active_devices == {"DISPLAY1"}
    assert ledger.exists()

    dimmer.restore_all()
    assert current["DISPLAY1"].red[255] == 65535
    assert current["DISPLAY1"].green[128] == 128 * 257
    assert dimmer.active_devices == set()
    assert not ledger.exists()


def test_silent_driver_rejection_falls_back_and_restores():
    original = identity_ramp()
    dimmer = GammaDimmer()
    writes = []
    dimmer._get = lambda _name: clone_ramp(original)
    dimmer._set = lambda _name, ramp: writes.append(clone_ramp(ramp)) or True

    assert dimmer.apply("DISPLAY1", 111) is None
    assert len(writes) == 2  # rejected target, then exact original restore
    assert writes[-1].red[255] == 65535
    assert dimmer.active_devices == set()


def test_next_instance_recovers_gamma_from_crash_ledger(tmp_path, monkeypatch):
    ledger = tmp_path / "gamma-session.json"
    original = identity_ramp()
    first = GammaDimmer(str(ledger))
    fake_driver(first, original)
    assert first.apply("DISPLAY1", 80) == 80
    assert ledger.exists()

    restored = []

    def record_restore(_self, name, ramp):
        restored.append((name, clone_ramp(ramp)))
        return True

    monkeypatch.setattr(GammaDimmer, "_set", record_restore)
    second = GammaDimmer(str(ledger))

    assert restored[0][0] == "DISPLAY1"
    assert restored[0][1].red[255] == 65535
    assert not ledger.exists()
    second.restore_all()


def test_very_dark_request_caps_gamma_for_overlay_remainder():
    original = identity_ramp()
    dimmer = GammaDimmer()
    current = fake_driver(dimmer, original)

    assert dimmer.apply("DISPLAY1", 200) == 127
    assert current["DISPLAY1"].red[255] == round(65535 * (128 / 255))
    dimmer.restore_all()


def test_corrupt_crash_ledger_is_removed_without_applying(tmp_path, monkeypatch):
    ledger = tmp_path / "gamma-session.json"
    ledger.write_text(json.dumps({"DISPLAY1": {"red": [1]}}))
    writes = []
    monkeypatch.setattr(
        GammaDimmer, "_set",
        lambda _self, name, ramp: writes.append((name, ramp)) or True)

    GammaDimmer(str(ledger))

    assert writes == []
    assert not ledger.exists()
