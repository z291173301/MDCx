from collections import OrderedDict

from mdcx.models.flags import JSON_DATA_CACHE_MAX_ENTRIES, Flags


def test_json_data_cache_is_bounded():
    Flags.reset()
    for index in range(JSON_DATA_CACHE_MAX_ENTRIES + 1):
        Flags.json_data_dic[f"N-{index}"] = index
        Flags.json_data_dic.move_to_end(f"N-{index}")
        while len(Flags.json_data_dic) > JSON_DATA_CACHE_MAX_ENTRIES:
            Flags.json_data_dic.popitem(last=False)

    assert isinstance(Flags.json_data_dic, OrderedDict)
    assert len(Flags.json_data_dic) == JSON_DATA_CACHE_MAX_ENTRIES
    assert "N-0" not in Flags.json_data_dic
    assert f"N-{JSON_DATA_CACHE_MAX_ENTRIES}" in Flags.json_data_dic
