import decomp_match as dm


READY = """3 candidates
542828  80 callees= 2 callers=  4 cantunwind
100abc  90 callees= 0 callers=  1 inline
"""


def test_parse_ready_skips_header_and_records_va():
    rows = dm.parse_ready(READY)
    assert rows[0]["offset_hex"] == "542828"
    assert rows[0]["va"] == 0x542828 + 0x100000
    assert rows[0]["symbol"] == "fn_542828"
    assert rows[1]["exidx"] == "inline"
    assert rows[0]["callees"] == 2
    assert rows[0]["backend"] == "ctrdecomp"


def test_extract_code_prefers_c_fence_after_note():
    text = "```text\nloads a table\n```\n```c\nint fn_542828(){return 1;}\n```"
    assert dm.extract_code(text).startswith("int fn_542828")
    assert dm.extract_fenced(text, "text") == "loads a table"


def test_ctr_prompt_stays_on_the_matching_gate():
    fn = dm.parse_ready(READY)[0]
    msgs = dm.build_messages(fn, "542828: bx lr", "int x;", "score 4", 2)
    blob = msgs[0]["content"] + msgs[1]["content"]
    assert "ARMCC" in blob
    assert "fn_542828" in blob
    assert "functions.toml" in blob
    assert "score 4" in blob


def test_binary_prompt_is_not_tied_to_3ds():
    fn = {
        "backend": "binary",
        "arch": "x64",
        "offset_hex": "1000",
        "size_hex": "20",
        "va": 0x140001000,
        "symbol": "fn_1000",
        "image": "demo.exe",
    }
    blob = "".join(m["content"] for m in dm.build_messages(fn, "140001000: ret", None, None, 1))
    assert "x64" in blob
    assert "fn_1000" in blob
    assert "ARMCC" not in blob
    assert "not claim the recovery is verified" in blob


def test_score_and_stop_rules():
    assert dm.parse_score("reloc +0x004 foo\nscore 0  target 12 ins  mine 12 ins") == 0
    assert dm.parse_score("compile failed") is None
    assert dm.next_action(0, 1, 3) == "pending_relink"
    assert dm.next_action(4, 1, 3) == "retry"
    assert dm.next_action(4, 3, 3) == "human"
    assert dm.next_action(None, 1, 3) == "unverified"
    assert dm.next_action(None, 1, 3, checked=True) == "checked"
    assert dm.next_action(None, 2, 3, checked=False) == "retry"
    assert dm.next_action(None, 3, 3, checked=False) == "human"


def test_disassemble_x64_slice():
    blob = bytes.fromhex("4889c890c3")  # mov rax, rcx; nop; ret
    text = dm.disassemble_bytes(blob, "x64", 0x1000)
    assert "mov" in text
    assert "ret" in text
    assert "00001000:" in text
