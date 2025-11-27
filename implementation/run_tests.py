#!/usr/bin/env python3
import os, sys, shutil, tempfile, difflib, json, argparse, hashlib
from os.path import isdir, isfile, join
from ap import apply_patch

TESTS = [
    ("01_basic_replace", "positive", None), ("02_sequences", "positive", None),
    ("03_tabs", "positive", None), ("04_spaces", "positive", None),
    ("05_crlf", "positive", None), ("06_short_anchor", "positive", None),
    ("07_empty_lines", "positive", None),
    ("08_error_snippet_not_found", "negative", "SNIPPET_NOT_FOUND"),
    ("09_error_anchor_not_found", "negative", "ANCHOR_NOT_FOUND"),
    ("10_error_ambiguous", "positive", None),
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
    ("23_error_range_ambiguous", "positive", None),
    ("24_heuristics", "positive", None),
    ("25_calculator_example", "positive", None),
    ("26_implicit_create_file", "positive", None),
    ("27_anchor_resolution", "positive", None),
    ("28_mixed_locators", "positive", None),
    ("29_anchor_overlap", "positive", None),
    ("30_locality_heuristic", "positive", None),
    ("31_redundant_snippet", "positive", None),
    ("32_intersection_resolution", "positive", None),
    ("33_snippet_locality", "positive", None),
    ("34_range_priority_strict", "positive", None),
    ("35_safe_create_empty", "positive", None),
    ("36_safe_create_fail", "negative", "FILE_EXISTS"),
    ("37_heuristic_end_eq_content", "positive", None),
    ("38_deep_scope", "positive", None),
    ("39_sequential_repeats", "positive", None),
    ("40_unified_snippet", "positive", None),
    ("41_indent_trailing_newline", "positive", None),
    ("42_strict_cursor", "negative", "SNIPPET_NOT_FOUND"),
    ("43_heuristic_implicit_create", "positive", None),
    ("44_rename", "positive", None),
    ("45_create_dir", "positive", None),
    ("46_delete_file_dir", "positive", None),
    ("47_error_mixed_atomic_delete", "negative", "INVALID_MODIFICATION"),
    ("48_comprehensive_delete", "positive", None),
    ("49_sequential_cursor", "positive", None),
    ("50_identical_snippet_tail", "positive", None),
    ("51_rename_create_dir", "positive", None),
    ("52_force_success_part", "positive", None),
    ("53_force_fail_report", "negative", "SNIPPET_NOT_FOUND"),
    ("54_crlf_preservation", "positive", None),
    ("55_rename_idempotency", "positive", None),
    ("56_insert_noop", "positive", None),
    ("57_explicit_lf", "positive", None),
    ("58_explicit_cr", "positive", None),
    ("59_error_create_file_on_dir", "negative", "FILE_WRITE_ERROR"),
    ("60_idempotent_create", "positive", None),
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
        "26_implicit_create_file": "dummy.txt",
        "27_anchor_resolution": "27_anchor_resolution.py",
        "28_mixed_locators": "28_mixed_locators.py",
        "29_anchor_overlap": "29_anchor_overlap.py",
        "26_indent_change": "26_indent_change.py",
        "30_locality_heuristic": "30_locality_heuristic.py",
        "31_redundant_snippet": "31_redundant_snippet.py",
        "32_intersection_resolution": "32_intersection_resolution.py",
        "33_snippet_locality": "33_snippet_locality.py",
        "34_range_priority_strict": "34_range_priority_strict.py",
        "35_safe_create_empty": "35_safe_create_empty.txt",
        "36_safe_create_fail": "36_safe_create_fail.txt",
        "37_heuristic_end_eq_content": "37_heuristic_end_eq_content.py",
        "38_deep_scope": "38_deep_scope.py",
        "39_sequential_repeats": "39_sequential_repeats.py",
        "40_unified_snippet": "40_unified_snippet.py",
        "41_indent_trailing_newline": "41_indent_trailing_newline.py",
        "42_strict_cursor": "42_strict_cursor.py",
        "43_heuristic_implicit_create": "dummy.txt",
        "44_rename": ["44_rename_src.txt", "44_rename_dir"],
        "45_create_dir": "dummy.txt",
        "46_delete_file_dir": ["to_be_deleted.txt", "to_be_deleted_dir"],
        "47_error_mixed_atomic_delete": "47_atomic_delete_source.txt",
        "48_comprehensive_delete": ["48_source.py", "48_file_to_delete.txt", "48_dir_to_delete"],
        "49_sequential_cursor": "49_sequential_cursor.py",
        "50_identical_snippet_tail": "50_identical_snippet_tail.py",
        "51_rename_create_dir": "51_rename_create_dir.txt",
        "52_force_success_part": ["52_atomic_src1.txt", "52_atomic_src2.txt"],
        "53_force_fail_report": ["52_atomic_src1.txt", "52_atomic_src2.txt"],
        "54_crlf_preservation": "54_crlf.txt",
        "55_rename_idempotency": "55_rename_src.txt",
        "56_insert_noop": "56_insert_noop.txt",
        "57_explicit_lf": "57_explicit_lf.txt",
        "58_explicit_cr": "58_explicit_cr.txt",
        "59_error_create_file_on_dir": "59_a_directory",
        "60_idempotent_create": "60_idempotent_create.txt",
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
    src_file = src_files[0] if src_files else None
    test_dir = tempfile.mkdtemp()
    try:
        if debug: print(f"\n{'='*20} RUNNING POSITIVE TEST: {test_name} {'='*20}")

        for src_path in src_files:
            if not os.path.exists(src_path): continue
            dest_path = os.path.join(test_dir, os.path.basename(src_path))
            if os.path.isdir(src_path):
                shutil.copytree(src_path, dest_path)
            else:
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                shutil.copy(src_path, dest_path)

        if test_name == "35_safe_create_empty":
             with open(os.path.join(test_dir, os.path.basename(src_file)), 'w') as f: pass
        if test_name == "54_crlf_preservation":
            src_in_test_dir = os.path.join(test_dir, os.path.basename(src_file))
            with open(src_in_test_dir, 'rb') as f:
                content = f.read()
            with open(src_in_test_dir, 'wb') as f:
                f.write(content.replace(b'\n', b'\r\n'))
        if test_name == "55_rename_idempotency":
            # Set up the special idempotency case: source does not exist, but destination does.
            src_in_test_dir = os.path.join(test_dir, os.path.basename(src_file))
            dest_in_test_dir = os.path.join(test_dir, "55_renamed.txt")

            with open(dest_in_test_dir, 'w') as f: f.write("This file exists.")
            if os.path.exists(src_in_test_dir):
                os.remove(src_in_test_dir)

            report = apply_patch(patch_file=patch_file, project_dir=test_dir, debug=debug)

            if report.get("status") == "SUCCESS" and not os.path.exists(src_in_test_dir) and os.path.exists(dest_in_test_dir):
                print(f"✅ PASSED: {test_name}"); return True
            else:
                print(f"❌ FAILED: {test_name}. Idempotency check failed."); return False

        force_apply = test_name == "52_force_success_part"
        report = apply_patch(patch_file=patch_file, project_dir=test_dir, debug=debug)

        if not force_apply and report.get("status") != "SUCCESS":
            print(f"❌ FAILED: {test_name}. Patcher errored on a valid patch: {report.get('error')}")
            return False

        if test_name == "44_rename":
            renamed_file, renamed_dir = join(test_dir, "44_renamed.txt"), join(test_dir, "44_renamed_dir")
            original_file, original_dir = join(test_dir, "44_rename_src.txt"), join(test_dir, "44_rename_dir")
            file_renamed, dir_renamed = isfile(renamed_file) and not os.path.exists(original_file), isdir(renamed_dir) and not os.path.exists(original_dir)
            if file_renamed and dir_renamed: print(f"✅ PASSED: {test_name}"); return True
            else: print(f"❌ FAILED: {test_name}. Rename op failed (file: {file_renamed}, dir: {dir_renamed})."); return False

        if test_name == "45_create_dir":
            if isdir(join(test_dir, "new_dir/")): print(f"✅ PASSED: {test_name}"); return True
            else: print(f"❌ FAILED: {test_name}. Directory creation failed."); return False

        if test_name == "46_delete_file_dir":
            deleted_file, deleted_dir = join(test_dir, "to_be_deleted.txt"), join(test_dir, "to_be_deleted_dir")
            if not os.path.exists(deleted_file) and not os.path.exists(deleted_dir): print(f"✅ PASSED: {test_name}"); return True
            else: print(f"❌ FAILED: {test_name}. Deletion failed (file_exists: {os.path.exists(deleted_file)}, dir_exists: {os.path.exists(deleted_dir)})."); return False

        if test_name == "51_rename_create_dir":
            renamed_file, original_file = join(test_dir, "new_parent_dir/renamed.txt"), join(test_dir, "51_rename_create_dir.txt")
            if isfile(renamed_file) and not os.path.exists(original_file): print(f"✅ PASSED: {test_name}"); return True
            else: print(f"❌ FAILED: {test_name}. Rename with dir creation failed."); return False

        if test_name == "13_create_file": actual_file_rel_path = "new/created_file.txt"
        elif test_name == "26_implicit_create_file": actual_file_rel_path = "26_implicit_create_file.txt"
        elif test_name == "43_heuristic_implicit_create": actual_file_rel_path = "43_created.txt"
        else: actual_file_rel_path = os.path.basename(src_file)

        actual_file_path = os.path.join(test_dir, actual_file_rel_path)
        if not os.path.exists(actual_file_path):
            print(f"❌ FAILED: {test_name}. Expected output file '{actual_file_rel_path}' not found."); return False

        with open(actual_file_path, 'rb') as f: actual_raw = f.read()

        expected_file_path = os.path.join("expected", actual_file_rel_path) if test_name in ["13_create_file", "26_implicit_create_file", "43_heuristic_implicit_create"] else expected_file
        with open(expected_file_path, 'rb') as f: expected_raw = f.read()

        if actual_raw == expected_raw:
            print(f"✅ PASSED: {test_name}"); return True
        else:
            print(f"❌ FAILED: {test_name}. Output does not match expected result.")
            actual, expected = actual_raw.decode('utf-8', 'replace'), expected_raw.decode('utf-8', 'replace')
            diff = difflib.unified_diff(expected.splitlines(keepends=True), actual.splitlines(keepends=True), fromfile=expected_file_path, tofile="actual_result")
            print("--- DIFF ---\n" + ''.join(diff)); return False
    finally:
        shutil.rmtree(test_dir)
def run_force_test(test_name, debug=False):
    src_files, patch_file, expected_file = get_paths(test_name)
    test_dir = tempfile.mkdtemp()
    output_capture = io.StringIO()
    try:
        if debug: print(f"\n{'='*20} RUNNING FORCE TEST: {test_name} {'='*20}")

        for src_path in src_files:
            if os.path.exists(src_path):
                shutil.copy(src_path, os.path.join(test_dir, os.path.basename(src_path)))

        with contextlib.redirect_stdout(output_capture), contextlib.redirect_stderr(output_capture):
            apply_patch(patch_file=patch_file, project_dir=test_dir, force=True, debug=debug)

        afailed_path = os.path.join(test_dir, "afailed.ap")
        if not os.path.exists(afailed_path):
            print(f"❌ FAILED: {test_name}. afailed.ap was not created.")
            print("--- CAPTURED OUTPUT ---\n" + output_capture.getvalue())
            return False

        with open(afailed_path, 'r', encoding='utf-8') as f_actual, \
             open(expected_file, 'r', encoding='utf-8') as f_expected:
            actual_content, expected_content = f_actual.read(), f_expected.read()
            if actual_content.strip() != expected_content.strip():
                print(f"❌ FAILED: {test_name}. afailed.ap content does not match expected.")
                diff = difflib.unified_diff(expected_content.splitlines(keepends=True), actual_content.splitlines(keepends=True), fromfile=expected_file, tofile="actual_afailed.ap")
                print("--- DIFF ---\n" + ''.join(diff))
                print("--- CAPTURED OUTPUT ---\n" + output_capture.getvalue())
                return False

        print(f"✅ PASSED: {test_name} (Correctly reported failure)")
        return True
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
                if os.path.isdir(src_path):
                    shutil.copytree(src_path, dest_path)
                else:
                    shutil.copy(src_path, dest_path)
                    with open(dest_path, 'rb') as f:
                        initial_hashes[os.path.basename(src_path)] = hashlib.md5(f.read()).hexdigest()

        # Test failure reporting file creation
        fail_report_path = os.path.join(test_dir, "failure.json")
        report = apply_patch(patch_file=patch_file, project_dir=test_dir, json_report=True, debug=debug, failure_report_path=fail_report_path)

        if report.get("status") != "FAILED":
            print(f"❌ FAILED: {test_name}. Expected FAILED status but got SUCCESS."); return False
        if report.get("error", {}).get("code") != expected_code:
            print(f"❌ FAILED: {test_name}. Expected '{expected_code}' but got "
                  f"'{report.get('error', {}).get('code')}'.\n" + json.dumps(report, indent=2)); return False

        # Verify failure report file was created
        if not os.path.exists(fail_report_path):
            print(f"❌ FAILED: {test_name}. Failure report file not created."); return False

        if expected_code == "SNIPPET_NOT_FOUND" and "fuzzy_matches" not in report.get("error", {}).get("context", {}):
            print(f"❌ FAILED: {test_name}. Expected 'fuzzy_matches' in error report."); return False

        final_hashes = {}
        for filename in initial_hashes.keys():
            with open(os.path.join(test_dir, filename), 'rb') as f:
                final_hashes[filename] = hashlib.md5(f.read()).hexdigest()

        if initial_hashes != final_hashes:
            print(f"❌ FAILED: {test_name}. Atomicity violated."); return False

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
            elif type == "negative":
                results.append(run_negative_test(name, code, debug=args.debug))
            elif type == "force":
                results.append(run_force_test(name, code, debug=args.debug))
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