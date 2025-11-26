#!/usr/bin/env python3
import os, sys, shutil, tempfile, difflib, json, argparse, hashlib
from ap import apply_patch

TESTS = [
    ("01_basic_replace", "positive", None), ("02_sequences", "positive", None),
    ("03_tabs", "positive", None), ("04_spaces", "positive", None),
    ("05_crlf", "positive", None), ("06_short_anchor", "positive", None),
    ("07_empty_lines", "positive", None),
    ("08_error_snippet_not_found", "negative", "SNIPPET_NOT_FOUND"),
    ("09_error_anchor_not_found", "negative", "ANCHOR_NOT_FOUND"),
    ("10_error_ambiguous", "negative", "AMBIGUOUS_MATCH"),
    ("11_error_invalid_header", "negative", "INVALID_PATCH_FILE"),
    ("12_error_invalid_spec", "negative", "INVALID_PATCH_FILE"),
    ("13_create_file", "positive", None),
    ("14_edge_cases", "positive", None),
    ("15_robustness", "positive", None),
    ("16_empty_actions", "positive", None),
    ("17_error_file_not_found", "negative", "FILE_NOT_FOUND"),
    ("18_idempotency", "positive", None),
    ("19_idempotency_noop", "positive", None),
    ("20_error_path_traversal", "negative", "INVALID_FILE_PATH"),
    ("21_error_atomic_failure", "negative", "SNIPPET_NOT_FOUND"),
    ("22_range_replace", "positive", None),
    ("23_error_range_ambiguous", "negative", "AMBIGUOUS_MATCH"),
    ("24_heuristics", "positive", None),
    ("25_calculator_example", "positive", None),
    ("27_anchor_resolution", "positive", None),
    ("28_mixed_locators", "positive", None),
    ("29_anchor_overlap", "positive", None),
]

def get_paths(test_name):
    patch_file = os.path.join("patches", f"{test_name}.ap")
    file_map = {
        "01_basic_replace": "01_basic.cpp", "02_sequences": "02_sequences.py",
        "03_tabs": "03_tabs.py", "04_spaces": "04_spaces.py", "05_crlf": "05_crlf.txt",
        "06_short_anchor": "06_short_anchor.py", "07_empty_lines": "07_empty_lines.py",
        "08_error_snippet_not_found": "08_error_src.py",
        "09_error_anchor_not_found": "09_error_src.py",
        "10_error_ambiguous": "10_error_src.py",
        "13_create_file": "dummy.txt",
        "14_edge_cases": "14_edge_cases.py",
        "15_robustness": "15_robustness.js",
        "16_empty_actions": "16_empty_actions.txt",
        "17_error_file_not_found": "dummy.txt",
        "11_error_invalid_header": "dummy.txt", "12_error_invalid_spec": "dummy.txt",
        "18_idempotency": "18_idempotency.py",
        "19_idempotency_noop": "19_idempotency_noop.py",
        "20_error_path_traversal": "dummy.txt",
        "21_error_atomic_failure": ["21_atomic_src1.txt", "21_atomic_src2.txt"],
"22_range_replace": "22_range_replace.py",
"23_error_range_ambiguous": "23_error_range_ambiguous.py",
"24_heuristics": "24_heuristics.py",
"25_calculator_example": "25_calculator.py",
"27_anchor_resolution": "27_anchor_resolution.py",
"28_mixed_locators": "28_mixed_locators.py",
"29_anchor_overlap": "29_anchor_overlap.py",
"26_indent_change": "26_indent_change.py",
    }
    src_filenames = file_map.get(test_name)
    if not src_filenames:
        sys.exit(f"Unknown test name: {test_name}")

    if isinstance(src_filenames, str):
        src_filenames = [src_filenames]

    src_paths = [os.path.join("src", fname) for fname in src_filenames]
    primary_expected_path = os.path.join("expected", src_filenames[0])

    return src_paths, patch_file, primary_expected_path

def run_positive_test(test_name, debug=False):
    src_files, patch_file, expected_file = get_paths(test_name)
    src_file = src_files[0] # Positive tests operate on a single primary file
    test_dir = tempfile.mkdtemp()
    try:
        if debug: print(f"\n{'='*20} RUNNING POSITIVE TEST: {test_name} {'='*20}")
        shutil.copy(src_file, os.path.join(test_dir, os.path.basename(src_file)))
        report = apply_patch(patch_file=patch_file, project_dir=test_dir, debug=debug)

        if report.get("status") != "SUCCESS":
            print(f"❌ FAILED: {test_name}. Patcher errored on a valid patch: {report.get('error')}")
            return False

        # Compare as raw bytes to correctly validate line endings (LF vs CRLF).
        actual_file_rel_path = "new/created_file.txt" if test_name == "13_create_file" else os.path.basename(src_file)

        with open(os.path.join(test_dir, actual_file_rel_path), 'rb') as f:
            actual_raw = f.read()

        expected_file_path = os.path.join("expected", actual_file_rel_path) if test_name == "13_create_file" else expected_file
        with open(expected_file_path, 'rb') as f:
            expected_raw = f.read()

        if actual_raw == expected_raw:
            print(f"✅ PASSED: {test_name}"); return True
        else:
            print(f"❌ FAILED: {test_name}. Output does not match expected result.")
            actual = actual_raw.decode('utf-8', 'replace')
            expected = expected_raw.decode('utf-8', 'replace')
            diff = difflib.unified_diff(
                expected.splitlines(keepends=True), actual.splitlines(keepends=True),
                fromfile=expected_file_path, tofile="actual_result"
            )
            print("--- DIFF ---\n" + ''.join(diff)); return False
    finally:
        shutil.rmtree(test_dir)

def run_negative_test(test_name, expected_code, debug=False):
    source_files, patch_file, _ = get_paths(test_name)
    test_dir = tempfile.mkdtemp()
    try:
        if debug: print(f"\n{'='*20} RUNNING NEGATIVE TEST: {test_name} {'='*20}")

        initial_hashes = {}
        for src_path in source_files:
            if os.path.exists(src_path):
                dest_path = os.path.join(test_dir, os.path.basename(src_path))
                shutil.copy(src_path, dest_path)
                with open(dest_path, 'rb') as f:
                    initial_hashes[os.path.basename(src_path)] = hashlib.md5(f.read()).hexdigest()

        report = apply_patch(patch_file=patch_file, project_dir=test_dir, json_report=True, debug=debug)

        if report.get("status") != "FAILED":
            print(f"❌ FAILED: {test_name}. Expected FAILED status but got SUCCESS."); return False
        if report.get("error", {}).get("code") != expected_code:
            print(f"❌ FAILED: {test_name}. Expected '{expected_code}' but got "
                  f"'{report.get('error', {}).get('code')}'.\n" + json.dumps(report, indent=2)); return False
        if expected_code == "SNIPPET_NOT_FOUND" and "fuzzy_matches" not in report.get("error", {}).get("context", {}):
            print(f"❌ FAILED: {test_name}. Expected 'fuzzy_matches' in error report."); return False

        final_hashes = {}
        for filename in initial_hashes.keys():
            with open(os.path.join(test_dir, filename), 'rb') as f:
                final_hashes[filename] = hashlib.md5(f.read()).hexdigest()

        if initial_hashes != final_hashes:
            print(f"❌ FAILED: {test_name}. Atomicity violated. Files were modified during a failed patch operation.")
            print(f"  Initial hashes: {initial_hashes}")
            print(f"  Final hashes:   {final_hashes}")
            return False

        print(f"✅ PASSED: {test_name} (Correctly failed as expected)"); return True
    finally:
        shutil.rmtree(test_dir)

def main():
    parser = argparse.ArgumentParser(description="Run the full test suite for the 'ap' patcher.")
    parser.add_argument("--debug", action="store_true", help="Enable detailed debug logging for each test.")
    args = parser.parse_args()

    print("===========================\n  Running `ap` Test Suite\n===========================\n")
    results = []
    for name, type, code in TESTS:
        try:
            if type == "positive":
                results.append(run_positive_test(name, debug=args.debug))
            else:
                results.append(run_negative_test(name, code, debug=args.debug))
        except Exception as e:
            print(f"❌ CRITICAL FAILURE in test '{name}': {e}"); results.append(False)

    passed, total = sum(results), len(results)
    print(f"\n===========================\n  Summary: {passed} / {total} tests passed.\n===========================")

    if all(results):
        print("✅ All tests passed successfully!"); sys.exit(0)
    else:
        print("❌ Some tests failed."); sys.exit(1)

if __name__ == '__main__':
    main()