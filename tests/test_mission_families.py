"""Pure-Python contract tests for the sidecar mission families."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import missions as M  # noqa: E402


def test_catalog_builds_all_three_distinct_families():
    missions = (
        M.create_mission(M.VEHICLE_THEFT, target_vehicle_id=17,
                         vehicle_name="Trans Am"),
        M.create_mission(M.SMASH_TARGETS, target_ids=("a", "b", "c")),
        M.create_mission(M.EVADE_HEAT),
    )

    assert tuple(m.family for m in missions) == M.MISSION_FAMILIES
    assert len({m.name for m in missions}) == 3
    assert all(m.status == M.OFFERED for m in missions)
    with pytest.raises(ValueError, match="unknown mission family"):
        M.create_mission("bowling_alley")


def test_vehicle_theft_requires_the_marked_ride_and_adjusts_payout_for_damage():
    mission = M.VehicleTheftMission(
        target_vehicle_id=17,
        vehicle_name="Trans Am",
        chop_shop_id="shop",
        reward=1000,
        time_limit_steps=100,
    )

    assert mission.start().stage == "steal"
    assert mission.on_event("vehicle_entered", vehicle_id=99).progress == 0
    acquired = mission.on_event("vehicle_entered", vehicle_id=17)
    assert acquired.stage == "deliver" and acquired.progress == 1

    mission.on_event("vehicle_exited", vehicle_id=17)
    assert mission.stage == "recover"
    mission.on_event("vehicle_entered", vehicle_id=17)
    wrong_car = mission.on_event(
        "location_reached", location_id="shop", vehicle_id=99, condition=1.0
    )
    assert wrong_car.status == M.ACTIVE

    result = mission.on_event(
        "location_reached", location_id="shop", vehicle_id=17, condition=0.4
    )
    assert result.complete
    assert result.reward_delta == 700
    assert mission.on_event("location_reached", location_id="shop",
                            vehicle_id=17).reward_delta == 0


def test_destroying_the_marked_vehicle_fails_the_theft_mission():
    mission = M.VehicleTheftMission(8, "delivery van", time_limit_steps=10)
    mission.start()
    ignored = mission.on_event("vehicle_destroyed", vehicle_id=9)
    assert ignored.status == M.ACTIVE

    failed = mission.on_event("vehicle_destroyed", vehicle_id=8)
    assert failed.failed and failed.reward_delta == 0
    assert failed.message == "THE MARKED RIDE IS SCRAP"


def test_smash_targets_count_once_ignore_bystanders_and_pay_once():
    mission = M.SmashTargetsMission(
        ("window", "sign", "hydrant"), reward=1500, time_limit_steps=30
    )
    mission.start()

    assert mission.on_event("target_smashed", target_id="mailbox").progress == 0
    assert mission.on_event("target_smashed", target_id="window").progress == 1
    assert mission.on_event("target_smashed", target_id="window").progress == 1
    assert mission.on_event("target_smashed", target_id="sign").progress == 2
    result = mission.on_event("target_smashed", target_id="hydrant")

    assert result.complete and result.progress_ratio == 1.0
    assert result.reward_delta == 1500
    assert mission.on_event("target_smashed", target_id="hydrant").reward_delta == 0


def test_getaway_resets_clean_clock_when_seen_then_requires_safehouse():
    mission = M.EvadeHeatMission(
        safehouse_id="hill", cool_steps=8, reward=1800, time_limit_steps=100
    )
    mission.start()

    mission.tick(3, wanted_level=0, spotted=False)
    assert mission.stage == "lay_low" and mission.progress == 3
    mission.tick(1, wanted_level=0, spotted=True)
    assert mission.stage == "break_contact" and mission.progress == 0
    mission.tick(4, wanted_level=1, spotted=False)
    assert mission.progress == 0
    cooled = mission.tick(8, wanted_level=0, spotted=False)
    assert cooled.stage == "reach_safehouse"
    assert cooled.status == M.ACTIVE

    assert mission.on_event("location_reached", location_id="arch").status == M.ACTIVE
    escaped = mission.on_event("location_reached", location_id="hill")
    assert escaped.complete and escaped.reward_delta == 1800


def test_timers_and_player_failure_events_are_terminal_and_idempotent():
    timeout = M.SmashTargetsMission((1,), time_limit_steps=3)
    assert timeout.tick(99).status == M.OFFERED
    timeout.start()
    result = timeout.tick(3)
    assert result.failed and result.steps_left == 0
    assert timeout.tick(1).message == "TIME RAN OUT"

    busted = M.VehicleTheftMission(1, "taxi", time_limit_steps=20)
    busted.start()
    result = busted.on_event("player_busted")
    assert result.failed and result.message == "BUSTED"
    assert busted.on_event("player_wasted").message == "BUSTED"


def test_validation_and_serializable_snapshot_are_integration_friendly():
    with pytest.raises(ValueError):
        M.SmashTargetsMission(())
    with pytest.raises(ValueError):
        M.SmashTargetsMission(("same", "same"))
    with pytest.raises(ValueError):
        M.EvadeHeatMission(cool_steps=0)

    mission = M.EvadeHeatMission(cool_steps=4, time_limit_steps=20)
    mission.start()
    with pytest.raises(ValueError, match="wanted_level"):
        mission.tick()
    with pytest.raises(ValueError, match="non-negative"):
        mission.tick(-1, wanted_level=0, spotted=False)

    payload = mission.snapshot().as_dict()
    assert payload["family"] == M.EVADE_HEAT
    assert payload["status"] == M.ACTIVE
    assert isinstance(payload["steps_left"], int)
