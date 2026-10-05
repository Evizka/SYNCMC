"""Instance artwork choices stay local, serializable and bounded by real hardware."""
import pytest

import mcsync as m


def test_instance_icon_choice_round_trips_with_instance_data(store):
    instance = store.create("Voxel world", icon="pickaxe")
    reloaded = store.load(instance.id)

    assert instance.icon == reloaded.icon == "pickaxe"
    assert reloaded.to_dict()["icon"] == "pickaxe"


def test_unknown_instance_icon_is_rejected(store):
    instance = store.create("Voxel world")

    with pytest.raises(m.UserError, match="иконка"):
        store.update(instance.id, icon="untrusted-path.png")


def test_ram_limit_is_detected_from_the_host_instead_of_a_fixed_slider_cap():
    limit = m.physical_memory_mb()

    assert isinstance(limit, int)
    assert limit >= 256
    assert limit <= 2_147_483_647
    if m.sys.platform.startswith("linux"):
        total_kib = next((int(line.split()[1]) for line in m.Path("/proc/meminfo").read_text().splitlines()
                          if line.startswith("MemTotal:")), 0)
        if total_kib:
            assert limit == total_kib // 1024
