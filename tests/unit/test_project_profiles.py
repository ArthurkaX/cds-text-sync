# -*- coding: utf-8 -*-
"""Default profile contract for readable project exports."""

from _project_profiles import enabled_projection_options, load_profile


def test_default_profile_enables_all_text_projections():
    profile = load_profile("default")
    projections = enabled_projection_options(profile, {})

    assert {item["id"] for item in projections} == {
        "pou_st",
        "pou_child_st",
        "gvl_st",
        "dut_st",
        "textlist_csv",
        "alarm_items_csv",
    }
