"""
Declarative test cases for the `ap` patcher.

Every case is one self-contained dict, so adding a regression test never means
touching a file map, a fixture directory and a name list in three places.

Recognised keys:
    name              test name (required)
    files             {relative path: content} written before the run
    patch             the .ap patch text
    strict            run the patcher in strict mode (default False)
    expect_status     "SUCCESS" | "PARTIAL" | "FAILED" (default "SUCCESS")
    expect_error      error code expected in the returned report
    expect_files      {relative path: exact expected content}
    expect_unchanged  [relative paths] that must keep their initial content
    expect_missing    [relative paths] that must not exist
    expect_md         [substrings] that must appear in afailed.md
"""

CASES = [
    {
        "name": "c04_markdown_fences_do_not_leak_into_the_source",
        "files": {"a.txt": "line1\nline2\nline3\n"},
        "patch": "```\naa000004 AP 3.2\n\naa000004 FILE\na.txt\n\naa000004 REPLACE\naa000004 snippet\nline2\naa000004 content\nLINE2\n```\n",
        "expect_files": {"a.txt": "line1\nLINE2\nline3\n"},
    },
    {
        "name": "c05_id_drift_keeps_both_ids_working",
        "files": {"a.txt": "line1\nline2\nline3\n"},
        "patch": ("aa000005 AP 3.2\n\naa000005 FILE\na.txt\n\n"
                  "aa000005 REPLACE\naa000005 snippet\nline1\naa000005 content\nLINE1\n\n"
                  "bb000005 REPLACE\nbb000005 snippet\nline2\nbb000005 content\nLINE2\n\n"
                  "aa000005 REPLACE\naa000005 snippet\nline3\naa000005 content\nLINE3\n"),
        "expect_files": {"a.txt": "LINE1\nLINE2\nLINE3\n"},
    },
    {
        "name": "c06_unknown_header_version_is_still_parsed",
        "files": {"a.txt": "line1\nline2\n"},
        "patch": "aa000006 AP 9.9\n\naa000006 FILE\na.txt\n\naa000006 REPLACE\naa000006 snippet\nline2\naa000006 content\nLINE2\n",
        "expect_files": {"a.txt": "line1\nLINE2\n"},
    },
    {
        "name": "c07_directive_case_and_colons_are_forgiven",
        "files": {"a.txt": "line1\nline2\n"},
        "patch": "aa000007 AP 3.2\n\naa000007 file:\na.txt\n\naa000007 replace\naa000007 SNIPPET:\nline2\naa000007 Content:\nLINE2\n",
        "expect_files": {"a.txt": "line1\nLINE2\n"},
    },
    {
        "name": "c08_missing_action_directive_splits_instead_of_losing_a_change",
        "files": {"a.txt": "one\ntwo\nthree\n"},
        "patch": ("aa000008 AP 3.2\n\naa000008 FILE\na.txt\n\n"
                  "aa000008 REPLACE\naa000008 snippet\none\naa000008 content\nONE\n\n"
                  "aa000008 snippet\nthree\naa000008 content\nTHREE\n"),
        "expect_files": {"a.txt": "ONE\ntwo\nTHREE\n"},
    },
    {
        "name": "c09_missing_snippet_keyword_is_recovered",
        "files": {"a.txt": "one\ntwo\n"},
        "patch": "aa000009 AP 3.2\n\naa000009 FILE\na.txt\n\naa000009 REPLACE\ntwo\naa000009 content\nTWO\n",
        "expect_files": {"a.txt": "one\nTWO\n"},
    },
    {
        "name": "c10_inline_file_path",
        "files": {"a.txt": "one\ntwo\n"},
        "patch": "aa000010 AP 3.2\n\naa000010 FILE a.txt\n\naa000010 REPLACE\naa000010 snippet\ntwo\naa000010 content\nTWO\n",
        "expect_files": {"a.txt": "one\nTWO\n"},
    },
    {
        "name": "c11_inline_file_path_with_newline_mode",
        "files": {"a.txt": "one\ntwo\n"},
        "patch": "aa000011 AP 3.2\n\naa000011 FILE CRLF a.txt\n\naa000011 REPLACE\naa000011 snippet\ntwo\naa000011 content\nTWO\n",
        "expect_files": {"a.txt": "one\r\nTWO\r\n"},
    },
    {
        "name": "c12_empty_file_path_is_a_clear_error",
        "files": {"a.txt": "one\n"},
        "patch": "aa000012 AP 3.2\n\naa000012 FILE\n\naa000012 REPLACE\naa000012 snippet\none\naa000012 content\nONE\n",
        "expect_status": "FAILED",
        "expect_error": "INVALID_PATCH_FILE",
        "expect_unchanged": ["a.txt"],
    },
    {
        "name": "c13_duplicate_content_is_rejected",
        "files": {"a.txt": "one\n"},
        "patch": ("aa000013 AP 3.2\n\naa000013 FILE\na.txt\n\naa000013 REPLACE\n"
                  "aa000013 snippet\none\naa000013 content\nONE\naa000013 content\nTWO\n"),
        "expect_status": "FAILED",
        "expect_error": "INVALID_PATCH_FILE",
        "expect_unchanged": ["a.txt"],
    },
    {
        "name": "c21_strict_rejects_the_missing_action_directive",
        "files": {"a.txt": "one\ntwo\nthree\n"},
        "strict": True,
        "patch": ("aa000021 AP 3.2\n\naa000021 FILE\na.txt\n\n"
                  "aa000021 REPLACE\naa000021 snippet\none\naa000021 content\nONE\n\n"
                  "aa000021 snippet\nthree\naa000021 content\nTHREE\n"),
        "expect_status": "FAILED",
        "expect_error": "INVALID_PATCH_FILE",
        "expect_unchanged": ["a.txt"],
    },
    {
        "name": "c22_strict_rejects_an_unsupported_version",
        "files": {"a.txt": "one\n"},
        "strict": True,
        "patch": "aa000022 AP 9.9\n\naa000022 FILE\na.txt\n\naa000022 REPLACE\naa000022 snippet\none\naa000022 content\nONE\n",
        "expect_status": "FAILED",
        "expect_error": "INVALID_PATCH_FILE",
        "expect_unchanged": ["a.txt"],
    },
    {
        "name": "c01_ambiguous_snippet_refuses_to_guess",
        "files": {"a.py": "def f():\n    a = 1\n    return a\n\ndef g():\n    a = 1\n    return a\n"},
        "patch": "aa000001 AP 3.2\n\naa000001 FILE\na.py\n\naa000001 REPLACE\naa000001 snippet\n    a = 1\naa000001 content\n    a = 42\n",
        "expect_status": "PARTIAL",
        "expect_unchanged": ["a.py"],
        "expect_md": ["AMBIGUOUS_MATCH", "anchor", "Current content of the file"],
    },
    {
        "name": "c02_anchor_resolves_the_ambiguity",
        "files": {"a.py": "def f():\n    a = 1\n    return a\n\ndef g():\n    a = 1\n    return a\n"},
        "patch": "aa000002 AP 3.2\n\naa000002 FILE\na.py\n\naa000002 REPLACE\naa000002 anchor\ndef g():\naa000002 snippet\n    a = 1\naa000002 content\n    a = 42\n",
        "expect_files": {"a.py": "def f():\n    a = 1\n    return a\n\ndef g():\n    a = 42\n    return a\n"},
    },
    {
        "name": "c03_repeated_locator_is_sequential_not_ambiguous",
        "files": {"a.txt": "x\nx\nx\n"},
        "patch": ("aa000003 AP 3.2\n\naa000003 FILE\na.txt\n\n"
                  "aa000003 REPLACE\naa000003 snippet\nx\naa000003 content\none\n\n"
                  "aa000003 REPLACE\naa000003 snippet\nx\naa000003 content\ntwo\n"),
        "expect_files": {"a.txt": "one\ntwo\nx\n"},
    },

    # ------------------------------------------------------------ chat noise
    {
        "name": "c14_dropped_indentation_is_restored",
        "files": {"a.py": "def f():\n    if x:\n        do_a()\n        do_b()\n"},
        "patch": "aa000014 AP 3.2\n\naa000014 FILE\na.py\n\naa000014 INSERT_AFTER\naa000014 snippet\ndo_a()\naa000014 content\ndo_c()\n",
        "expect_files": {"a.py": "def f():\n    if x:\n        do_a()\n        do_c()\n        do_b()\n"},
    },
    {
        "name": "c15_explicit_indentation_is_never_touched",
        "files": {"a.py": "def f():\n    if x:\n        do_a()\n        do_b()\n"},
        "patch": "aa000015 AP 3.2\n\naa000015 FILE\na.py\n\naa000015 INSERT_AFTER\naa000015 snippet\ndo_a()\naa000015 content\n        do_c()\n",
        "expect_files": {"a.py": "def f():\n    if x:\n        do_a()\n        do_c()\n        do_b()\n"},
    },
    {
        "name": "c16_partial_line_snippet_gets_an_actionable_message",
        "files": {"a.py": "def f():\n    x = compute(1, 2) + 1\n"},
        "patch": "aa000016 AP 3.2\n\naa000016 FILE\na.py\n\naa000016 REPLACE\naa000016 snippet\ncompute(1, 2)\naa000016 content\n    x = compute(3, 4) + 1\n",
        "expect_status": "PARTIAL",
        "expect_unchanged": ["a.py"],
        "expect_md": ["fragment of an existing line", "SNIPPET_NOT_FOUND"],
    },
    {
        "name": "c17_reversed_range_is_auto_corrected",
        "files": {"a.txt": "keep\nstart\nmiddle\nend\nkeep2\n"},
        "patch": ("aa000017 AP 3.2\n\naa000017 FILE\na.txt\n\naa000017 REPLACE\n"
                  "aa000017 snippet\nend\naa000017 snippet_tail\nstart\naa000017 content\nNEW\n"),
        "expect_files": {"a.txt": "keep\nNEW\nkeep2\n"},
    },
    {
        "name": "c18_point_action_with_a_range_inserts_at_the_range_edge",
        "files": {"a.txt": "start\nmiddle\nend\ntail\n"},
        "patch": ("aa000018 AP 3.2\n\naa000018 FILE\na.txt\n\naa000018 INSERT_AFTER\n"
                  "aa000018 snippet\nstart\naa000018 snippet_tail\nend\naa000018 content\nNEW\n"),
        "expect_files": {"a.txt": "start\nmiddle\nend\nNEW\ntail\n"},
    },

    # ----------------------------------------------------------- output shape
    {
        "name": "c20_untouched_files_are_not_rewritten",
        "files": {"a.txt": "one\ntwo"},
        "patch": "aa000020 AP 3.2\n\naa000020 FILE\na.txt\n\naa000020 REPLACE\naa000020 snippet\nnope\naa000020 content\nNOPE\n",
        "expect_status": "PARTIAL",
        "expect_unchanged": ["a.txt"],
    },

    # ------------------------------------------------------------ strict mode
    {
        "name": "c23_strict_is_atomic_across_files",
        "files": {"a.txt": "one\n", "b.txt": "two\n"},
        "strict": True,
        "patch": ("aa000023 AP 3.2\n\naa000023 FILE\na.txt\n\naa000023 REPLACE\n"
                  "aa000023 snippet\none\naa000023 content\nONE\n\n"
                  "aa000023 FILE\nb.txt\n\naa000023 REPLACE\naa000023 snippet\nmissing\n"
                  "aa000023 content\nX\n"),
        "expect_status": "FAILED",
        "expect_error": "SNIPPET_NOT_FOUND",
        "expect_unchanged": ["a.txt", "b.txt"],
    },

    # ------------------------------------------------------------ the report
    {
        "name": "c24_report_shows_what_was_already_applied",
        "files": {"a.txt": "one\ntwo\n"},
        "patch": ("aa000024 AP 3.2\n\naa000024 FILE\na.txt\n\n"
                  "aa000024 REPLACE\naa000024 snippet\none\naa000024 content\nONE\n\n"
                  "aa000024 REPLACE\naa000024 snippet\nmissing line\naa000024 content\nX\n"),
        "expect_status": "PARTIAL",
        "expect_files": {"a.txt": "ONE\ntwo\n"},
        "expect_md": ["already changed in this file", "-one", "+ONE", "The patch that failed"],
    },
    {
        "name": "c25_clean_rerun_removes_the_stale_report",
        "files": {"a.txt": "one\n", "afailed.md": "# stale report\n"},
        "patch": "aa000025 AP 3.2\n\naa000025 FILE\na.txt\n\naa000025 REPLACE\naa000025 snippet\none\naa000025 content\nONE\n",
        "expect_files": {"a.txt": "ONE\n"},
        "expect_missing": ["afailed.md"],
    },
    {
        "name": "c26_an_ap_example_inside_content_is_not_mistaken_for_drift",
        "files": {"doc.md": "old\n"},
        "patch": ("aa000026 AP 3.2\n\naa000026 FILE\ndoc.md\n\naa000026 RECREATE\naa000026 content\n"
                  "Example:\n\n```\ne4a2f1b8 FILE\nx.py\n\ne4a2f1b8 REPLACE\ne4a2f1b8 snippet\n"
                  "old\ne4a2f1b8 content\nnew\n```\n\nEnd."),
        "expect_files": {"doc.md": "Example:\n\n```\ne4a2f1b8 FILE\nx.py\n\ne4a2f1b8 REPLACE\n"
                                   "e4a2f1b8 snippet\nold\ne4a2f1b8 content\nnew\n```\n\nEnd.\n"},
    },
        {
            "name": "c27_cli_entry_point_is_importable_and_consistent",
            "files": {"a.txt": "one\n"},
            "patch": "aa000027 AP 3.2\n\naa000027 FILE\na.txt\n\naa000027 REPLACE\naa000027 snippet\none\naa000027 content\nONE\n",
            "expect_files": {"a.txt": "ONE\n"},
        },
        {
            "name": "c28_redundant_project_prefix_creation",
            "files": {"src/a.txt": "old content\n"},
            "patch": (
                "bb000028 AP 3.2\n\n"
                "bb000028 FILE\n"
                "my_project/src/new_file.txt\n\n"
                "bb000028 CREATE\n"
                "bb000028 content\n"
                "New file created successfully!\n"
            ),
        "expect_files": {
            "src/new_file.txt": "New file created successfully!\n"
        },
        },
        {
            "name": "c29_redundant_project_prefix_existing_file",
            "files": {"src/a.txt": "old content\n"},
            "patch": (
                "cc000029 AP 3.2\n\n"
                "cc000029 FILE\n"
                "my_project/src/a.txt\n\n"
                "cc000029 REPLACE\n"
                "cc000029 snippet\n"
                "old content\n"
                "cc000029 content\n"
                "new content\n"
            ),
            "expect_files": {
                "src/a.txt": "new content\n"
            },
        },
{
        "name": "c30_locator_never_matches_text_the_patch_itself_wrote",
        "files": {"m.py": "def a():\n    log(\"start\")\n    return 1\n\ndef b():\n    return 2\n"},
        "patch": ("aa000030 AP 3.2\n\naa000030 FILE\nm.py\n\n"
                  "aa000030 INSERT_AFTER\naa000030 snippet\ndef b():\n"
                  "aa000030 content\n    log(\"start\")\n\n"
                  "aa000030 REPLACE\naa000030 snippet\nlog(\"start\")\n"
                  "aa000030 content\n    log(\"BEGIN\")\n"),
        "expect_files": {"m.py": "def a():\n    log(\"BEGIN\")\n    return 1\n\ndef b():\n    log(\"start\")\n    return 2\n"},
    },
    {
        "name": "c31_idempotency_probe_does_not_match_its_own_output",
        "files": {"m.py": "def a(x):\n    old_a()\n\ndef b(x):\n    old_b()\n"},
        "patch": ("aa000031 AP 3.2\n\naa000031 FILE\nm.py\n\n"
                  "aa000031 REPLACE\naa000031 snippet\nold_a()\naa000031 content\ncheck(x)\n\n"
                  "aa000031 REPLACE\naa000031 snippet\nold_bb()\naa000031 content\ncheck(x)\n"),
        "expect_status": "PARTIAL",
        "expect_md": ["Snippet not found"],
        "expect_files": {"m.py": "def a(x):\n    check(x)\n\ndef b(x):\n    old_b()\n"},
    },
    {
        "name": "c32_single_line_locator_does_not_eat_a_line_prefix",
        "files": {"m.py": "class C:\n    def __init__(self):\n        self.count = 0\n"},
        "patch": ("aa000032 AP 3.2\n\naa000032 FILE\nm.py\n\n"
                  "aa000032 REPLACE\naa000032 snippet\ncount = 0\naa000032 content\ncount = 5\n"),
        "expect_status": "PARTIAL",
        "expect_unchanged": ["m.py"],
    },
    {
        "name": "c33_single_line_locator_still_ignores_list_numbering",
        "files": {"m.py": "# 1. First item\n# 2. Second item\n"},
        "patch": ("aa000033 AP 3.2\n\naa000033 FILE\nm.py\n\n"
                  "aa000033 REPLACE\naa000033 snippet\nFirst item\naa000033 content\n# First item (replaced)\n"),
        "expect_files": {"m.py": "# First item (replaced)\n# 2. Second item\n"},
    },
    {
        "name": "c34_empty_content_followed_by_a_directive_is_a_delete",
        "files": {"a.txt": "a\nb\nc\n"},
        "patch": ("aa000034 AP 3.2\n\naa000034 FILE\na.txt\n\n"
                  "aa000034 REPLACE\naa000034 snippet\nb\naa000034 content\n\n"
                  "aa000034 REPLACE\naa000034 snippet\nc\naa000034 content\nC\n"),
        "expect_files": {"a.txt": "a\nC\n"},
    },
    {
        "name": "c35_empty_content_at_end_of_patch_is_treated_as_truncation",
        "files": {"a.txt": "a\nb\nc\n"},
        "patch": ("aa000035 AP 3.2\n\naa000035 FILE\na.txt\n\n"
                  "aa000035 REPLACE\naa000035 snippet\nb\naa000035 content\n"),
        "expect_status": "PARTIAL",
        "expect_unchanged": ["a.txt"],
        "expect_md": ["PATCH_TRUNCATED"],
    },
    {
        "name": "c36_end_directive_proves_a_trailing_empty_content_is_deliberate",
        "files": {"a.txt": "a\nb\nc\n"},
        "patch": ("aa000036 AP 3.2\n\naa000036 FILE\na.txt\n\n"
                  "aa000036 REPLACE\naa000036 snippet\nb\naa000036 content\n\naa000036 END\n"),
        "expect_files": {"a.txt": "a\nc\n"},
    },
    {
        "name": "c37_top_level_block_is_not_inserted_inside_a_function",
        "files": {"main.go": "package main\n\nfunc A(x int) int {\n\treturn 0\n}\n\nfunc C() {}\n"},
        "patch": ("aa000037 AP 3.2\n\naa000037 FILE\nmain.go\n\n"
                  "aa000037 INSERT_AFTER\naa000037 snippet\nfunc A(x int) int {\n"
                  "aa000037 content\nfunc B(x int) int {\n\treturn x + 1\n}\n"),
        "expect_files": {"main.go": "package main\n\nfunc A(x int) int {\n\treturn 0\n}\n\nfunc B(x int) int {\n\treturn x + 1\n}\n\nfunc C() {}\n"},
    },
    {
        "name": "c38_nested_block_is_left_where_the_model_put_it",
        "files": {"main.go": "package main\n\nfunc A() {\n\tx := 1\n\t_ = x\n}\n"},
        "patch": ("aa000038 AP 3.2\n\naa000038 FILE\nmain.go\n\n"
                  "aa000038 INSERT_AFTER\naa000038 snippet\nx := 1\n"
                  "aa000038 content\n\tgo func() {\n\t\twork()\n\t}()\n"),
        "expect_files": {"main.go": "package main\n\nfunc A() {\n\tx := 1\n\tgo func() {\n\t\twork()\n\t}()\n\t_ = x\n}\n"},
    },
    {
        "name": "c39_scope_end_replaces_a_whole_brace_block",
        "files": {"main.go": "package main\n\nfunc A(x int) int {\n\tif x > 0 {\n\t\treturn x\n\t}\n\treturn 0\n}\n\nfunc C() {}\n"},
        "patch": ("aa000039 AP 3.2\n\naa000039 FILE\nmain.go\n\n"
                  "aa000039 REPLACE\naa000039 snippet\nfunc A(x int) int {\n"
                  "aa000039 scope_end 1\n"
                  "aa000039 content\nfunc A(x int) int {\n\treturn x\n}\n"),
        "expect_files": {"main.go": "package main\n\nfunc A(x int) int {\n\treturn x\n}\n\nfunc C() {}\n"},
    },
    {
        "name": "c40_scope_end_deletes_a_whole_indented_block",
        "files": {"m.py": "def a(x):\n    if x:\n        return 1\n    return 0\n\ndef b(x):\n    return 2\n"},
        "patch": ("aa000040 AP 3.2\n\naa000040 FILE\nm.py\n\n"
                  "aa000040 DELETE\naa000040 snippet\ndef a(x):\n"
                  "aa000040 scope_end 1\naa000040 include_trailing_blank_lines 1\n"),
        "expect_files": {"m.py": "def b(x):\n    return 2\n"},
    },
{
        "name": "c41_locator_removed_by_an_earlier_modification_is_named_as_such",
        "files": {"m.py": "def a(x):\n    log(\"hi\")\n    return x\n\ndef b(x):\n    return 2\n"},
        "patch": ("aa000041 AP 3.2\n\naa000041 FILE\nm.py\n\n"
                  "aa000041 REPLACE\naa000041 snippet\ndef a(x):\naa000041 scope_end 1\n"
                  "aa000041 content\ndef a(x):\n    return x * 2\n\n"
                  "aa000041 REPLACE\naa000041 snippet\nlog(\"hi\")\n"
                  "aa000041 content\n    log(\"bye\")\n"),
        "expect_status": "PARTIAL",
        "expect_md": ["LOCATOR_CONSUMED"],
        "expect_files": {"m.py": "def a(x):\n    return x * 2\ndef b(x):\n    return 2\n"},
    },
    {
        "name": "c42_anchor_duplicated_by_the_patch_itself_stays_unambiguous",
        "files": {"m.py": "def a():\n    setup()\n    work()\n\ndef b():\n    work()\n"},
        "patch": ("aa000042 AP 3.2\n\naa000042 FILE\nm.py\n\n"
                  "aa000042 INSERT_BEFORE\naa000042 snippet\ndef b():\n"
                  "aa000042 content\ndef c():\n    setup()\n\n"
                  "aa000042 REPLACE\naa000042 anchor\ndef b():\n"
                  "aa000042 snippet\nwork()\naa000042 content\n    work2()\n"),
        "expect_files": {"m.py": "def a():\n    setup()\n    work()\n\ndef c():\n    setup()\ndef b():\n    work2()\n"},
    },
    {
        "name": "c43_unbalanced_result_is_reported",
        "files": {"main.go": "package main\n\nfunc A() {\n\tif true {\n\t\twork()\n\t}\n}\n"},
        "patch": ("aa000043 AP 3.2\n\naa000043 FILE\nmain.go\n\n"
                  "aa000043 REPLACE\naa000043 snippet\nif true {\n"
                  "aa000043 snippet_tail\nwork()\n"
                  "aa000043 content\n\twork2()\n"),
        "expect_stdout": ["off by -1"],
    },
{
        "name": "c44_rewritten_file_gains_a_trailing_newline",
        "files": {"f.txt": "a\nb"},
        "patch": ("aa000044 AP 3.2\n\naa000044 FILE\nf.txt\n\n"
                  "aa000044 REPLACE\naa000044 snippet\nb\naa000044 content\nB\n"),
        "expect_files": {"f.txt": "a\nB\n"},
    },
    {
        "name": "c45_untouched_file_is_not_given_a_trailing_newline",
        "files": {"f.txt": "a\nb", "g.txt": "x\n"},
        "patch": ("aa000045 AP 3.2\n\naa000045 FILE\ng.txt\n\n"
                  "aa000045 REPLACE\naa000045 snippet\nx\naa000045 content\nX\n"),
        "expect_files": {"g.txt": "X\n"},
        "expect_unchanged": ["f.txt"],
    },
    {
        "name": "c46_trailing_newline_uses_the_files_own_line_ending",
        "files": {"f.txt": "a\r\nb"},
        "patch": ("aa000046 AP 3.2\n\naa000046 FILE\nf.txt\n\n"
                  "aa000046 REPLACE\naa000046 snippet\nb\naa000046 content\nB\n"),
        "expect_files": {"f.txt": "a\r\nB\r\n"},
    },
]
