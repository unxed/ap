import os, sys, shutil, tempfile, difflib, json, argparse
from ap import apply_patch

TESTS = [
    ("01_basic_replace", "positive", None), ("02_sequences", "positive", None),
    ("03_tabs", "positive", None), ("04_spaces", "positive", None),
    ("05_crlf", "positive", None), ("06_short_anchor", "positive", None),
    ("07_empty_lines", "positive", None),
    ("08_error_snippet_not_found", "negative", "SNIPPET_NOT_FOUND"),
    ("09_error_anchor_not_found", "negative", "ANCHOR_NOT_FOUND"),
    ("10_error_ambiguous", "negative", "AMBIGUOUS_MATCH"),
    ("11_error_invalid_yaml", "negative", "INVALID_PATCH_FILE"),
    ("12_error_invalid_spec", "negative", "INVALID_MODIFICATION"),
    ("13_create_file", "positive", None),
    ("14_edge_cases", "positive", None),
    ("15_robustness", "positive", None),
    ("16_empty_actions", "positive", None),
    ("17_error_file_not_found", "negative", "FILE_NOT_FOUND"),
    ("18_idempotency", "positive", None),
    ("19_idempotency_noop", "positive", None),
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
        "11_error_invalid_yaml": "dummy.txt", "12_error_invalid_spec": "dummy.txt",
        "18_idempotency": "18_idempotency.py",
        "19_idempotency_noop": "19_idempotency_noop.py",
    }
    src_filename = file_map.get(test_name)
    if not src_filename:
        sys.exit(f"Unknown test name: {test_name}")
    return os.path.join("src", src_filename), patch_file, os.path.join("expected", src_filename)

def run_positive_test(test_name, debug=False):
    src_file, patch_file, expected_file = get_paths(test_name)
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
    src_file, patch_file, _ = get_paths(test_name)
    test_dir = tempfile.mkdtemp()
    try:
        if debug: print(f"\n{'='*20} RUNNING NEGATIVE TEST: {test_name} {'='*20}")
        if os.path.exists(src_file):
            shutil.copy(src_file, os.path.join(test_dir, os.path.basename(src_file)))

        report = apply_patch(patch_file=patch_file, project_dir=test_dir, json_report=True, debug=debug)

        if report.get("status") != "FAILED":
            print(f"❌ FAILED: {test_name}. Expected FAILED status but got SUCCESS."); return False
        if report.get("error", {}).get("code") != expected_code:
            print(f"❌ FAILED: {test_name}. Expected '{expected_code}' but got "
                  f"'{report.get('error', {}).get('code')}'.\n" + json.dumps(report, indent=2)); return False
        if expected_code == "SNIPPET_NOT_FOUND" and "fuzzy_matches" not in report.get("error", {}).get("context", {}):
            print(f"❌ FAILED: {test_name}. Expected 'fuzzy_matches' in error report."); return False

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