"""Unit tests for bot/tables.py — the monospace text-table helper."""

from bot.tables import code_block, display_width, pad, render_table


class TestDisplayWidth:
    def test_ascii_is_one_column_each(self):
        assert display_width("EPS") == 3
        assert display_width("") == 0

    def test_cjk_is_two_columns_each(self):
        assert display_width("台積電") == 6

    def test_mixed_cjk_and_ascii(self):
        # 每股EPS(元) → 每股(4) + EPS(3) + ()(2) + 元(2) = 11
        assert display_width("每股EPS(元)") == 11

    def test_fullwidth_punctuation_counts_two(self):
        assert display_width("，") == 2


class TestPad:
    def test_left_pad_appends_spaces(self):
        assert pad("AB", 5, "left") == "AB   "

    def test_right_pad_prepends_spaces(self):
        assert pad("AB", 5, "right") == "   AB"

    def test_center_pad_splits_gap(self):
        assert pad("AB", 6, "center") == "  AB  "

    def test_cjk_padding_uses_display_width(self):
        # 台積電 is 6 columns; pad to 10 → 4 trailing spaces.
        assert pad("台積電", 10, "left") == "台積電    "

    def test_no_pad_when_already_wide_enough(self):
        assert pad("ABCDE", 3) == "ABCDE"


class TestRenderTable:
    def test_columns_align_by_display_width(self):
        table = render_table(
            ["指標", "2025", "2024"],
            [["每股EPS", 66.26, 45.25], ["ROE", "28%", "27%"]],
        )
        lines = table.splitlines()
        # Header, divider, two data rows.
        assert len(lines) == 4
        # First column left-aligned: rows start with the label.
        assert lines[2].startswith("每股EPS")
        assert lines[3].startswith("ROE")

    def test_number_columns_right_aligned_by_default(self):
        table = render_table(["名稱", "值"], [["a", 1], ["bbbb", 200]])
        lines = table.splitlines()
        # The value column is right-aligned so single/triple digits line up
        # on their right edge.
        assert lines[2].rstrip().endswith("1")
        assert lines[3].rstrip().endswith("200")
        # Column width of value = max(len("值")=2, "200"=3) = 3; "1" padded to
        # width 3 → "  1".
        assert "  1" in lines[2]

    def test_short_rows_are_padded(self):
        table = render_table(["a", "b", "c"], [["x"]])
        # Should not raise and should render three columns.
        assert table.splitlines()[2].startswith("x")

    def test_extra_cells_dropped(self):
        table = render_table(["a", "b"], [["x", "y", "z"]])
        assert "z" not in table

    def test_cjk_header_and_rows_stay_aligned(self):
        table = render_table(
            ["公司", "代號"],
            [["台積電", "2330"], ["聯電", "2303"]],
        )
        lines = table.splitlines()
        # Divider length equals the max display width of the widest line.
        widths = {display_width(ln) for ln in lines}
        # All lines share the same display width (aligned block).
        assert len(widths) == 1

    def test_empty_headers_returns_empty_string(self):
        assert render_table([], []) == ""

    def test_no_rows_still_renders_header_and_divider(self):
        table = render_table(["A", "B"], [])
        lines = table.splitlines()
        assert len(lines) == 2
        assert lines[0].startswith("A")
        assert set(lines[1]) == {"-"}

    def test_custom_alignment(self):
        table = render_table(
            ["a", "b"], [["x", "y"]], aligns=["right", "left"]
        )
        assert "x" in table and "y" in table


class TestCodeBlock:
    def test_wraps_in_triple_backticks(self):
        out = code_block("hello")
        assert out.startswith("```\n")
        assert out.endswith("\n```")
        assert "hello" in out

    def test_defangs_internal_triple_backticks(self):
        out = code_block("a ``` b")
        # No raw triple-backtick remains inside the body (only the two fences).
        assert out.count("```") == 2

    def test_roundtrip_with_render_table(self):
        table = render_table(["名稱", "值"], [["EPS", 66.26]])
        block = code_block(table)
        assert "EPS" in block
        assert "66.26" in block
        assert block.startswith("```")


class TestCodeBlockCapped:
    def test_short_body_unchanged(self):
        from bot.tables import code_block, code_block_capped

        assert code_block_capped("hello") == code_block("hello")

    def test_long_body_capped_to_limit(self):
        from bot.tables import code_block_capped

        out = code_block_capped("x" * 5000, limit=4096)
        assert len(out) <= 4096
        assert out.startswith("```") and out.endswith("```")

    def test_backticks_near_limit_still_within_limit(self):
        # Regression for the 4096 off-by: escaping ``` -> ``\u200b` grows the
        # string, so a naive "slice to limit-8 then wrap" could overshoot.
        from bot.tables import code_block_capped

        body = "```" * 1400  # ~4200 chars, all backticks that expand on escape
        out = code_block_capped(body, limit=4096)
        assert len(out) <= 4096

    def test_result_is_valid_fence(self):
        from bot.tables import code_block_capped

        out = code_block_capped("a" * 9000, limit=4096)
        assert out.startswith("```\n")
        assert out.endswith("\n```")

    def test_custom_limit(self):
        from bot.tables import code_block_capped

        out = code_block_capped("a" * 100, limit=20)
        assert len(out) <= 20
