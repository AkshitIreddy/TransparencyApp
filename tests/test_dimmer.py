from transparency_app.dimmer import MAX_DIM_ALPHA, ScreenDimmer


def test_monitor_intensities_have_independent_values():
    dimmer = ScreenDimmer()
    dimmer.set_intensity(100)
    dimmer.set_monitor_intensity("DISPLAY1", 25)
    dimmer.set_monitor_intensity("DISPLAY2", 175)

    assert dimmer.intensity_for("DISPLAY1") == 25
    assert dimmer.intensity_for("DISPLAY2") == 175
    assert dimmer.intensity_for("NEW_DISPLAY") == 100
    assert dimmer._alpha("DISPLAY1") == 25
    assert dimmer._alpha("DISPLAY2") == 175


def test_monitor_intensities_are_clamped_and_copied():
    dimmer = ScreenDimmer()
    levels = {"DISPLAY1": -10, "DISPLAY2": 500}
    dimmer.set_intensities(levels)
    levels["DISPLAY1"] = 90

    assert dimmer.intensities == {"DISPLAY1": 0, "DISPLAY2": MAX_DIM_ALPHA}
    returned = dimmer.intensities
    returned["DISPLAY1"] = 80
    assert dimmer.intensity_for("DISPLAY1") == 0
