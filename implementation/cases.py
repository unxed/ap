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
]