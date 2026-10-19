from cleansweep.llm import FakeLLM


def test_fake_llm_matches_substring():
    llm = FakeLLM({"judge": '[{"item_id": "a"}]'})
    assert llm.chat_json([{"role": "user", "content": "please judge"}]) == [{"item_id": "a"}]
    assert llm.chat_json([{"role": "user", "content": "other"}]) == {}
    assert llm.chat([{"role": "user", "content": "other"}]) == "ok"
    assert llm.usage()["llm_calls"] == 3
