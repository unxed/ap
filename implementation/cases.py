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
]