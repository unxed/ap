#!/usr/bin/env python3
import os
import argparse
import difflib
import json
import re
from typing import Optional, Tuple, List, Dict, Any

def visualize_str(s: str) -> str:
    """Makes special characters visible for debugging."""
    if not isinstance(s, str): return repr(s)
    return s.replace('\t', '\\t').replace('\r', '\\r').replace('\n', '\\n\n')

def debug_print(debug_flag: bool, title: str, **kwargs):
    """Prints a formatted debug message if the debug flag is set."""
    if not debug_flag: return
    print(f"\n--- DEBUG: {title} ---")
    for key, value in kwargs.items():
        if isinstance(value, str) and len(value) > 80:
            print(f"  {key} (len={len(value)}):")
            print(f"    Visualized: {visualize_str(value[:200])}... (truncated)")
        else:
            print(f"  {key}: {visualize_str(value)}")
    print("--------------------" + "-" * len(title))

def parse_ap3_format(patch_file: str) -> Dict[str, Any]:
    """Parses the AP 3.0 delimiter-based format into the standard internal dict structure."""
    with open(patch_file, 'r', encoding='utf-8') as f:
        lines = f.read().splitlines()

    patch_id = None
    data = {'version': '3.0', 'changes': []}
    current_file_change = None
    current_modification = None
    reading_key = None
    value_lines = []
    pending_args = None # To store args for delayed processing (e.g. CREATE_FILE)

    header_pattern = re.compile(r'^([a-z0-9]{8})\s+AP\s+3\.0$')
    directive_pattern = None

    line_iterator = iter(enumerate(lines, 1))

    # Find header and patch_id
    for line_num, line in line_iterator:
        stripped_line = line.strip()
        if not stripped_line or stripped_line.startswith('#'):
            continue
        match = header_pattern.match(stripped_line)
        if not match: raise ValueError(f"Invalid AP 3.0 header on line {line_num}.")
        patch_id = match.group(1)
        directive_pattern = re.compile(rf'^{re.escape(patch_id)}\s+(.*)$')
        break

    if not patch_id: return data

    # Main parsing loop
    for line_num, line in line_iterator:
        match = directive_pattern.match(line)
        if match:
            if reading_key:
                start = 0
                while start < len(value_lines) and not value_lines[start].strip(): start += 1
                end = len(value_lines)
                while end > start and not value_lines[end - 1].strip(): end -= 1
                value = "\n".join(value_lines[start:end])

                if reading_key == "path" and current_file_change:
                    current_file_change['file_path'] = value
                elif reading_key == "CREATE_FILE_PATH":
                    # Implicit file creation support
                    if value:
                        current_file_change = {'modifications': []}
                        data['changes'].append(current_file_change)
                        current_file_change['file_path'] = value
                        if pending_args in {'LF', 'CRLF', 'CR'}: current_file_change['newline'] = pending_args

                    if not current_file_change: raise ValueError(f"Action 'CREATE_FILE' on line {line_num} (prev) before FILE.")
                    current_modification = {'action': 'CREATE_FILE'}
                    current_file_change['modifications'].append(current_modification)
                elif current_modification:
                    current_modification[reading_key] = value

                reading_key, value_lines, pending_args = None, [], None

            parts = match.group(1).strip().split(maxsplit=1)
            key, args = parts[0], parts[1] if len(parts) > 1 else None

            ACTIONS = {'REPLACE', 'INSERT_AFTER', 'INSERT_BEFORE', 'DELETE'}
            VALUE_KEYS = {'snippet', 'anchor', 'content', 'end_snippet'}
            ARG_KEYS = {'include_leading_blank_lines', 'include_trailing_blank_lines'}
            FILE_STARTERS = {'CREATE_FILE'} # Treated as hybrid Action/Value
            NEWLINE_VALS = {'LF', 'CRLF', 'CR'}

            if key == 'FILE':
                current_file_change = {'modifications': []}
                data['changes'].append(current_file_change)
                if args and args in NEWLINE_VALS: current_file_change['newline'] = args
                current_modification, reading_key = None, 'path'
            elif key in ACTIONS:
                if not current_file_change: raise ValueError(f"Action '{key}' on line {line_num} before FILE.")
                current_modification = {'action': key}
                current_file_change['modifications'].append(current_modification)
            elif key in FILE_STARTERS:
                # Hybrid: acts as key-value (for path) AND action.
                # Logic deferred to flush phase to check if value exists.
                reading_key = 'CREATE_FILE_PATH'
                pending_args = args
            elif key in VALUE_KEYS:
                if args: raise ValueError(f"Directive '{key}' on line {line_num} takes no arguments.")
                if key != 'path' and not current_modification: raise ValueError(f"'{key}' on line {line_num} outside modification.")
                reading_key = key
            elif key in ARG_KEYS:
                if not current_modification: raise ValueError(f"'{key}' on line {line_num} outside modification.")
                if not args: raise ValueError(f"Directive '{key}' on line {line_num} requires an argument.")
                try: current_modification[key] = int(args)
                except ValueError: raise ValueError(f"Argument for '{key}' on line {line_num} must be an integer.")
            elif key in NEWLINE_VALS:
                if not current_file_change: raise ValueError(f"Newline '{key}' on line {line_num} before FILE.")
                current_file_change['newline'] = key
            else: raise ValueError(f"Unknown directive '{key}' on line {line_num}.")

        elif reading_key: value_lines.append(line)
        elif line.strip(): raise ValueError(f"Unexpected content on line {line_num}: '{line}'")

    if reading_key:
        start = 0
        while start < len(value_lines) and not value_lines[start].strip(): start += 1
        end = len(value_lines)
        while end > start and not value_lines[end - 1].strip(): end -= 1
        value = "\n".join(value_lines[start:end])

        if reading_key == "path" and current_file_change:
            current_file_change['file_path'] = value
        elif reading_key == "CREATE_FILE_PATH":
            if value:
                current_file_change = {'modifications': []}
                data['changes'].append(current_file_change)
                current_file_change['file_path'] = value
                if pending_args in {'LF', 'CRLF', 'CR'}: current_file_change['newline'] = pending_args
            if not current_file_change: raise ValueError(f"Action 'CREATE_FILE' at end of file before FILE.")
            current_modification = {'action': 'CREATE_FILE'}
            current_file_change['modifications'].append(current_modification)
        elif current_modification:
            current_modification[reading_key] = value

    return data

def detect_line_endings(file_path: str) -> str:
    try:
        with open(file_path, 'rb') as f:
            chunk = f.read(1024)
            if b'\r\n' in chunk: return '\r\n'
            if b'\n' in chunk: return '\n'
            if b'\r' in chunk: return '\r'
    except (IOError, FileNotFoundError): pass
    return os.linesep

def get_fuzzy_matches(content: str, snippet: str, cutoff: float = 0.7) -> List[Dict[str, Any]]:
    """
    Finds multi-line fuzzy matches for a snippet within content using a sliding window.
    """
    if not snippet or not snippet.strip():
        return []

    # Normalize the snippet once: remove blank lines and strip each line.
    normalized_snippet_lines = [line.strip() for line in snippet.strip().splitlines() if line.strip()]
    if not normalized_snippet_lines:
        return []

    snippet_as_block = "\n".join(normalized_snippet_lines)
    window_size = len(normalized_snippet_lines)

    # Normalize the source content, but keep track of original line numbers.
    source_lines_with_meta = [
        (i + 1, line.strip())
        for i, line in enumerate(content.splitlines())
        if line.strip()
    ]

    matches = []
    # Iterate through the normalized source content with a sliding window.
    for i in range(len(source_lines_with_meta) - window_size + 1):
        window_meta = source_lines_with_meta[i : i + window_size]

        original_line_numbers = [meta[0] for meta in window_meta]
        window_lines = [meta[1] for meta in window_meta]
        window_as_block = "\n".join(window_lines)

        # Compare the entire block from the snippet with the window block.
        ratio = difflib.SequenceMatcher(None, snippet_as_block, window_as_block).ratio()

        if ratio >= cutoff:
            # To display the match, we retrieve the original, unstripped lines.
            original_content_lines = content.splitlines()
            start_line_idx = original_line_numbers[0] - 1
            end_line_idx = original_line_numbers[-1]
            original_text_block = "\n".join(original_content_lines[start_line_idx:end_line_idx])

            matches.append({
                "line_number": original_line_numbers[0],
                "score": round(ratio, 4),
                "text": original_text_block
            })

    return sorted(matches, key=lambda x: x['score'], reverse=True)[:3]

def smart_find(content: str, snippet: str) -> List[Tuple[int, int]]:
    original_lines = content.splitlines(keepends=True)
    snippet_lines = [line for line in (snippet or "").strip().splitlines() if line.strip()]
    if not snippet_lines: return []
    normalized_snippet_lines = [line.strip() for line in snippet_lines]
    occurrences = []
    for i in range(len(original_lines)):
        if not original_lines[i].strip(): continue
        content_lines_found, end_line_index = [], i - 1
        temp_j = i
        while len(content_lines_found) < len(snippet_lines) and temp_j < len(original_lines):
            line = original_lines[temp_j]
            if line.strip(): content_lines_found.append(line)
            end_line_index = temp_j
            temp_j += 1

        if len(content_lines_found) == len(snippet_lines):
            normalized_content_lines = [line.strip() for line in content_lines_found]
            # HYBRID SEARCH: First line is suffix, rest are exact match.
            first_line_match = normalized_content_lines[0].endswith(normalized_snippet_lines[0])
            tail_match = normalized_content_lines[1:] == normalized_snippet_lines[1:]
            if first_line_match and tail_match:
                start_pos = len("".join(original_lines[:i]))
                end_pos = len("".join(original_lines[:end_line_index + 1]))
                occurrences.append((start_pos, end_pos))
    return occurrences

def find_target_in_content(content: str, anchor: Optional[str], snippet: str, debug: bool = False, last_match_end: int = 0) -> Tuple[Optional[Tuple[int, int]], Dict[str, Any]]:
    search_space, offset, anchor_found = content, 0, None

    if anchor:
        debug_print(debug, "ANCHOR SEARCH", anchor=anchor)
        anchor_occurrences = smart_find(content, anchor)
        if not anchor_occurrences:
            return None, {"code": "ANCHOR_NOT_FOUND", "message": "Anchor not found.", "context": {"anchor": anchor}}

        # === CURSOR FILTERING FOR ANCHORS ===
        # If we have a history of changes, prefer anchors that appear AFTER the last change.
        if len(anchor_occurrences) > 1 and last_match_end > 0:
            forward_anchors = [a for a in anchor_occurrences if a[0] >= last_match_end]
            if forward_anchors:
                debug_print(debug, "ANCHOR CURSOR FILTER", message=f"Filtered {len(anchor_occurrences)} -> {len(forward_anchors)} based on cursor {last_match_end}")
                anchor_occurrences = forward_anchors

        # === DEEP SCOPE RESOLUTION ===
        # If anchor is still ambiguous, check if the snippet exists uniquely inside one of the anchor scopes.
        if len(anchor_occurrences) > 1:
            debug_print(debug, "DEEP SCOPE SEARCH", message=f"Anchor ambiguous ({len(anchor_occurrences)} matches). Checking snippets in scopes.")
            valid_scopes = []

            # Pre-calculate all snippet occurrences to optimize
            all_snippet_occurrences = smart_find(content, snippet)

            for a_idx, (a_start, a_end) in enumerate(anchor_occurrences):
                # Scope extends to the start of the next anchor candidate or end of file
                # (Simple heuristic: finding the snippet strictly after this anchor)

                # Check 1: Are there any snippets after this anchor?
                snippets_after = [s for s in all_snippet_occurrences if s[0] >= a_end]

                if snippets_after:
                    first_snip = snippets_after[0]
                    # Check 2 (Shadowing): Is there ANOTHER anchor strictly between this anchor and the snippet?
                    is_shadowed = any(other_a[0] > a_end and other_a[0] < first_snip[0] for other_a in anchor_occurrences)

                    if not is_shadowed:
                        valid_scopes.append((a_start, a_end))

            if len(valid_scopes) == 1:
                 anchor_occurrences = valid_scopes
                 debug_print(debug, "AMBIGUITY RESOLVED (DEEP SCOPE)", position=anchor_occurrences[0][0])
            # If 0 or >1 valid scopes, we fall through to the ambiguity error below.

        if len(anchor_occurrences) > 1:
            return None, {"code": "AMBIGUOUS_ANCHOR", "message": f"Anchor found {len(anchor_occurrences)} times and ambiguity could not be resolved.", "context": {"anchor": anchor, "count": len(anchor_occurrences)}}

        anchor_start, anchor_end = anchor_occurrences[0]

        # === ROBUST OVERLAP DETECTION ===
        s_lines = [l.strip() for l in (snippet or "").strip().splitlines() if l.strip()]
        a_lines = [l.strip() for l in (anchor or "").strip().splitlines() if l.strip()]
        is_overlap = False
        if s_lines and a_lines:
            # Check 1: Full inclusion (Snippet starts with Anchor)
            if len(s_lines) >= len(a_lines) and s_lines[:len(a_lines)] == a_lines:
                is_overlap = True
            # Check 2: Partial overlap (Anchor ends with Snippet start)
            elif a_lines[-1] == s_lines[0]:
                is_overlap = True

        if is_overlap:
             debug_print(debug, "OVERLAP DETECTED", message="Snippet overlaps with Anchor. Including Anchor in search scope.")
             search_space, offset, anchor_found = content[anchor_start:], anchor_start, True
        else:
             search_space, offset, anchor_found = content[anchor_end:], anchor_end, True

    debug_print(debug, "SNIPPET SEARCH", snippet=snippet, search_space_len=len(search_space))
    occurrences = smart_find(search_space, snippet)

    # === SNIPPET CURSOR FILTER ===
    # If multiple snippets found, strictly prefer the first one after the cursor.
    if len(occurrences) > 1:
        forward_occurrences = [o for o in occurrences if (o[0] + offset) >= last_match_end]
        if forward_occurrences:
            occurrences = [forward_occurrences[0]]
            debug_print(debug, "SNIPPET AMBIGUITY RESOLVED (CURSOR)", position=occurrences[0][0])

    if not occurrences:
        preview_lines = [l for l in search_space.splitlines() if l.strip()]
        context = {
            "snippet": snippet,
            "anchor": anchor,
            "anchor_found": anchor_found,
            "fuzzy_matches": get_fuzzy_matches(search_space, snippet),
            "search_space_preview": "\n".join(preview_lines[:7])
        }
        return None, {"code": "SNIPPET_NOT_FOUND", "message": "Snippet not found.", "context": context}

    if len(occurrences) > 1 and not anchor:
        return None, {"code": "AMBIGUOUS_MATCH", "message": f"Snippet found {len(occurrences)} times.", "context": {"snippet": snippet, "count": len(occurrences)}}

    start_pos, end_pos = occurrences[0]
    return (start_pos + offset, end_pos + offset), {}

def apply_patch(patch_file: str, project_dir: str, dry_run: bool = False, json_report: bool = False, debug: bool = False, force: bool = False, failure_report_path: str = None, create_failure_case: bool = False) -> Dict[str, Any]:
    patch_content = ""
    try:
        with open(patch_file, 'r', encoding='utf-8') as f:
            patch_content = f.read()
    except (IOError, FileNotFoundError):
        # Let parse_ap3_format handle the error reporting.
        # patch_content will be empty, which is acceptable for the failure case report.
        pass

    def create_failure_case_file(filename: str, details: Dict[str, Any], original_content: Optional[str]):
        """Creates a detailed log file for a failed patch application for debugging."""
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write("--- BEGIN ERROR DETAILS ---\n")
                f.write(json.dumps(details, indent=2))
                f.write("\n--- END ERROR DETAILS ---\n\n")

                f.write("--- BEGIN ORIGINAL TARGET FILE CONTENT ---\n")
                f.write(original_content or "[Original file content not available for this error type]")
                if not (original_content or "").endswith('\n'):
                    f.write('\n')
                f.write("\n--- END ORIGINAL TARGET FILE CONTENT ---\n\n")

                f.write("--- BEGIN FAILED PATCH FILE CONTENT ---\n")
                f.write(patch_content)
                if not patch_content.endswith('\n'):
                    f.write('\n')
                f.write("\n--- END FAILED PATCH FILE CONTENT ---\n")
            if not json_report:
                print(f"Created failure case report: {filename}")
        except IOError as e:
            if not json_report:
                print(f"ERROR: Could not write failure case report to {filename}: {e}")

    def report_error(details):
        if failure_report_path:
            try:
                with open(failure_report_path, 'w', encoding='utf-8') as f:
                    json.dump(details, f, indent=2)
                if not json_report: print(f"Failure report saved to: {failure_report_path}")
            except IOError as e:
                print(f"Failed to save failure report: {e}")

        if not json_report:
            file_info = f" in file '{details.get('file_path')}'" if details.get('file_path') else ""
            mod_info = f" (modification #{details['mod_idx'] + 1})" if 'mod_idx' in details else ""
            print(f"\nERROR{file_info}{mod_info}: {details['error']['message']}")
            ctx = details['error'].get('context', {})

            def print_block(name, value):
                print(f"  {name}:")
                for line in (value or "").strip().splitlines():
                    print(f"    {line}")

            for key in ['anchor', 'snippet', 'end_snippet']:
                if ctx.get(key): print_block(key.replace('_', ' ').title(), ctx[key])

            if ctx.get('anchor_found') and ctx.get('search_space_preview'):
                print("  Context following found anchor (Actual File Content):")
                for line in ctx['search_space_preview'].splitlines():
                    print(f"    {line}")

            if ctx.get('fuzzy_matches'):
                print("  Did you mean one of these?")
                for match in ctx['fuzzy_matches']:
                    print(f"    Line {match['line_number']} (Score: {match['score']}):")
                    # FIX: Properly print multi-line 'text' from fuzzy match
                    print("      Actual:")
                    for line in (match['text'] or "").splitlines():
                        print(f"        {visualize_str(line)}")

                    expected_first = (ctx.get('snippet') or "").strip().splitlines()
                    if expected_first:
                        print(f"      Expected (first line): {visualize_str(expected_first[0])}")

        return details

    if force and os.path.exists("afailed.ap"):
        err_msg = "afailed.ap exists. Please remove or rename it before running with --force."
        if json_report: return {"status": "FAILED", "error": {"code": "AFAILED_EXISTS", "message": err_msg}}
        print(f"ERROR: {err_msg}")
        exit(1)

    try: data = parse_ap3_format(patch_file)
    except (ValueError, FileNotFoundError) as e:
        err_details = {"status": "FAILED", "error": { "code": "INVALID_PATCH_FILE", "message": str(e) }}
        if create_failure_case:
            create_failure_case_file("afailed.log", err_details, None)
        return report_error(err_details)

    patch_id_str = "00000000"
    try:
        with open(patch_file, 'r', encoding='utf-8') as f:
            for line in f:
                match = re.match(r'^([a-z0-9]{8})\s+AP\s+3\.0$', line.strip())
                if match: patch_id_str = match.group(1); break
    except: pass

    failed_changes_output = []
    write_plan = []

    for change in data.get('changes', []):
        if 'file_path' not in change:
            err_details = {"status": "FAILED", "error": {"code": "INVALID_PATCH_FILE", "message": "Missing 'file_path' for a change block."}}
            if create_failure_case:
                create_failure_case_file("afailed.log", err_details, None)
            return report_error(err_details)
        relative_path = change['file_path']

        real_project_dir = os.path.realpath(project_dir)
        real_file_path = os.path.realpath(os.path.join(project_dir, relative_path))
        if not real_file_path.startswith(os.path.join(real_project_dir, '')):
            err_details = {"status": "FAILED", "file_path": relative_path, "error": {"code": "INVALID_FILE_PATH", "message": "Path traversal detected."}}
            if create_failure_case:
                create_failure_case_file("afailed.log", err_details, None)
            return report_error(err_details)

        file_path = os.path.join(project_dir, relative_path)
        newline_mode = change.get('newline')
        newline_char = {'LF': '\n', 'CRLF': '\r\n', 'CR': '\r'}.get(newline_mode) or (detect_line_endings(file_path) if os.path.exists(file_path) else os.linesep)
        debug_print(debug, "PLANNING FOR FILE", file=file_path, newline_mode=newline_mode or "DETECTED", detected_newline=newline_char)

        original_content = ""
        try:
            with open(file_path, 'r', encoding='utf-8', newline=None) as f: original_content = f.read()
            file_existed = True
        except FileNotFoundError:
            file_existed = False
            if any(mod.get('action') == 'CREATE_FILE' for mod in change.get('modifications', [])): original_content = ""
            else:
                err_details = {"status": "FAILED", "file_path": relative_path, "error": { "code": "FILE_NOT_FOUND", "message": "Target file not found." }}
                if create_failure_case:
                    create_failure_case_file("afailed.log", err_details, "") # File not found, content is empty
                return report_error(err_details)

        internal_newline = '\n'
        working_content = original_content.replace('\r\n', internal_newline).replace('\r', internal_newline)
        last_mod_end_pos = 0

        for mod_idx, mod in enumerate(change.get('modifications', [])):
            action = mod.get('action')
            debug_print(debug, f"MODIFICATION #{mod_idx+1}", action=action)
            if not action:
                err_details = {"status": "FAILED", "file_path": relative_path, "mod_idx": mod_idx, "error": {"code": "INVALID_MODIFICATION", "message": "'action' is required."}}
                if create_failure_case:
                    create_failure_case_file("afailed.log", err_details, original_content)
                return report_error(err_details)

            content_to_add = mod.get('content', '')

            # === SAFE CREATE FILE ===
            if action == 'CREATE_FILE':
                if os.path.exists(file_path):
                    with open(file_path, 'r', encoding='utf-8', newline=None) as f_check:
                        existing_content = f_check.read().replace('\r\n', internal_newline).replace('\r', internal_newline)

                    normalized_existing = "\n".join(l.strip() for l in existing_content.strip().splitlines())
                    normalized_new = "\n".join(l.strip() for l in (content_to_add or "").strip().splitlines())

                    if normalized_existing == normalized_new:
                        debug_print(debug, "IDEMPOTENCY SKIP", message="File exists with matching content.", file_path=file_path)
                        break
                    elif not existing_content.strip():
                        debug_print(debug, "OVERWRITE EMPTY", message="File exists but is empty. Overwriting.")
                        pass
                    else:
                        err_details = {"status": "FAILED", "file_path": relative_path, "mod_idx": mod_idx, "error": {"code": "FILE_EXISTS", "message": "Target file exists and is not empty."}}
                        if create_failure_case:
                            create_failure_case_file("afailed.log", err_details, original_content)
                        return report_error(err_details)

                working_content = (content_to_add or "").replace('\r\n', internal_newline).replace('\r', internal_newline)
                break

            snippet_val = mod.get('snippet')
            end_snippet = mod.get('end_snippet')

            # Heuristic: If end_snippet is identical to content, the AI likely confused "what to replace" with "what to replace it with".
            # Treat this as a point-based replacement.
            if snippet_val and end_snippet and content_to_add:
                norm_end = "\n".join(l.strip() for l in end_snippet.strip().splitlines())
                norm_content = "\n".join(l.strip() for l in content_to_add.strip().splitlines())
                if norm_end == norm_content:
                    debug_print(debug, "HEURISTIC APPLIED", message="end_snippet matches content. Treating as single snippet.")
                    end_snippet = None

            # Heuristic: Auto-correct AI error where end_snippet is part of snippet (now snippet_val).
            if snippet_val and end_snippet and snippet_val.strip().endswith(end_snippet.strip()):
                debug_print(debug, "HEURISTIC APPLIED", message="end_snippet is suffix of snippet. Treating as single snippet.")
                end_snippet = None

            target_pos, error = None, {}

            # Logic: If end_snippet exists, it is a range operation starting at snippet_val.
            # If only snippet_val exists, it is a point operation.

            if end_snippet is not None:
                if snippet_val is None:
                    err_details = {"status": "FAILED", "file_path": relative_path, "mod_idx": mod_idx, "error": {"code": "INVALID_MODIFICATION", "message": "Range requires 'snippet'."}}
                    if create_failure_case:
                        create_failure_case_file("afailed.log", err_details, original_content)
                    return report_error(err_details)
                if action not in ['REPLACE', 'DELETE']:
                    err_details = {"status": "FAILED", "file_path": relative_path, "mod_idx": mod_idx, "error": {"code": "INVALID_MODIFICATION", "message": f"Action '{action}' does not support range."}}
                    if create_failure_case:
                        create_failure_case_file("afailed.log", err_details, original_content)
                    return report_error(err_details)

                start_pos_info, error = find_target_in_content(working_content, mod.get('anchor'), snippet_val, debug, last_mod_end_pos)
                if not error:
                    start_range_begin, start_range_end = start_pos_info
                    end_occurrences = smart_find(working_content[start_range_end:], end_snippet)
                    if not end_occurrences:
                        error = {"code": "END_SNIPPET_NOT_FOUND", "message": "End snippet not found.", "context": {"snippet": snippet_val, "end_snippet": end_snippet}}
                    else:
                        end_range_begin_rel, end_range_end_rel = end_occurrences[0]
                        target_pos = (start_range_begin, start_range_end + end_range_end_rel)

            elif snippet_val is not None:
                 target_pos, error = find_target_in_content(working_content, mod.get('anchor'), snippet_val, debug, last_mod_end_pos)

            elif action != 'CREATE_FILE':
                err_details = {"status": "FAILED", "file_path": relative_path, "mod_idx": mod_idx, "error": {"code": "INVALID_MODIFICATION", "message": "Modification requires locators."}}
                if create_failure_case:
                    create_failure_case_file("afailed.log", err_details, original_content)
                return report_error(err_details)

            if error:
                is_idempotency_skip = False
                error_codes = ['SNIPPET_NOT_FOUND', 'ANCHOR_NOT_FOUND', 'END_SNIPPET_NOT_FOUND']
                if action == 'DELETE' and error['code'] in error_codes:
                    debug_print(debug, "IDEMPOTENCY SKIP", message="Snippet to delete is already gone.", snippet=snippet_val); is_idempotency_skip = True
                if action == 'REPLACE' and error['code'] in error_codes:
                    content_pos, _ = find_target_in_content(working_content, mod.get('anchor'), content_to_add or "", debug=False)
                    if content_pos: debug_print(debug, "IDEMPOTENCY SKIP", message="Snippet not found, but replacement content exists.", snippet=snippet_val); is_idempotency_skip = True

                if is_idempotency_skip: continue

                report = {"status": "FAILED", "file_path": relative_path, "mod_idx": mod_idx, "error": error}
                report['error']['context']['action'] = action
                if force:
                    print(f"  - FAILED: Mod #{mod_idx + 1} ({mod.get('action')}) in '{relative_path}'. Reason: {error.get('message')}")
                    if create_failure_case:
                        create_failure_case_file(f"afailed.{mod_idx}.log", report, original_content)
                    failed_file_block = next((item for item in failed_changes_output if item.get('file_path') == relative_path), None)
                    if not failed_file_block:
                        failed_file_block = {'file_path': relative_path, 'modifications': []}
                        if change.get('newline'): failed_file_block['newline'] = change.get('newline')
                        failed_changes_output.append(failed_file_block)
                    failed_file_block['modifications'].append(mod)
                    continue
                else:
                    if create_failure_case:
                        create_failure_case_file("afailed.log", report, original_content)
                    return report_error(report)

            if action == 'CREATE_FILE': continue
            last_mod_end_pos = target_pos[0]
            start_pos, end_pos = target_pos

            for key, val in [('include_leading_blank_lines', -1), ('include_trailing_blank_lines', 1)]:
                count = mod.get(key, 0)
                if count > 0:
                    pos, direction = (start_pos, -1) if val == -1 else (end_pos, 1)
                    for _ in range(count):
                        next_newline = working_content.rfind(internal_newline, 0, pos -1) if direction == -1 else working_content.find(internal_newline, pos)
                        if next_newline == -1:
                            if (working_content[:pos] if direction == -1 else working_content[pos:]).strip() == "": pos = 0 if direction == -1 else len(working_content)
                            break
                        line_content = working_content[next_newline + 1:pos] if direction == -1 else working_content[pos:next_newline]
                        if line_content.strip() == "": pos = next_newline + 1 if direction == -1 else next_newline + 1
                        else: break
                    if val == -1: start_pos = pos
                    else: end_pos = pos

            def normalize_block(text): return "\n".join(l.strip() for l in (text or "").strip().splitlines())

            if action == 'REPLACE' and normalize_block(working_content[start_pos:end_pos]) == normalize_block(content_to_add): debug_print(debug, "IDEMPOTENCY SKIP", message="REPLACE content already present."); continue
            elif action == 'INSERT_AFTER' and normalize_block(working_content[end_pos:]).startswith(normalize_block(content_to_add)): debug_print(debug, "IDEMPOTENCY SKIP", message="INSERT_AFTER content already present."); continue
            elif action == 'INSERT_BEFORE' and normalize_block(working_content[:start_pos]).endswith(normalize_block(content_to_add)): debug_print(debug, "IDEMPOTENCY SKIP", message="INSERT_BEFORE content already present."); continue

            if action == 'DELETE':
                working_content = working_content[:start_pos] + working_content[end_pos:]
                continue

            indented_content = content_to_add or ""
            if action in ['REPLACE', 'INSERT_AFTER', 'INSERT_BEFORE'] and content_to_add:
                line_start_pos = working_content.rfind(internal_newline, 0, start_pos) + 1
                indentation = ""
                for char in working_content[line_start_pos:start_pos]:
                    if char in ' \t': indentation += char
                    else: break

                debug_print(debug, "INDENTATION LOGIC", detected_indent=indentation)
                if not content_to_add:
                    indented_content = ""
                else:
                    lines = content_to_add.split(internal_newline)
                    indented_content = internal_newline.join([indentation + line for line in lines])
                original_had_trailing_newline = end_pos > start_pos and working_content[end_pos-1] == internal_newline
                if action in ['INSERT_AFTER', 'INSERT_BEFORE'] or (action == 'REPLACE' and original_had_trailing_newline):
                    if not content_to_add.endswith('\n'):
                        indented_content += internal_newline

            if action == 'REPLACE':
                working_content = working_content[:start_pos] + indented_content + working_content[end_pos:]
            elif action == 'INSERT_AFTER':
                working_content = working_content[:end_pos] + indented_content + working_content[end_pos:]
            elif action == 'INSERT_BEFORE':
                working_content = working_content[:start_pos] + indented_content + working_content[start_pos:]
            if force:
                print(f"  + SUCCESS: Mod #{mod_idx + 1} ({action}) applied.")

        final_content = newline_char.join([line.rstrip(' \t') for line in working_content.split(internal_newline)])
        if final_content != original_content or not file_existed:
            write_plan.append((file_path, final_content, relative_path))

    if not write_plan and failed_changes_output:
        return {"status": "FAILED", "error": {"code": "MODIFICATION_FAILED", "message": "One or more modifications failed."}}

    if force and failed_changes_output:
        with open("afailed.ap", "w", encoding="utf-8") as f:
            f.write(f"# Summary: Failed changes from a forced patch application.\n\n")
            f.write(f"{patch_id_str} AP 3.0\n\n")
            for change_item in failed_changes_output:
                f.write(f"{patch_id_str} FILE")
                if change_item.get("newline"): f.write(f" {change_item['newline']}")
                f.write(f"\n{change_item['file_path']}\n\n")
                for mod_item in change_item['modifications']:
                    f.write(f"{patch_id_str} {mod_item['action']}\n")
                    for key in ['anchor', 'snippet', 'end_snippet', 'content']:
                        if key in mod_item: f.write(f"{patch_id_str} {key}\n{mod_item[key]}\n")
                    for key in ['include_leading_blank_lines', 'include_trailing_blank_lines']:
                        if key in mod_item: f.write(f"{patch_id_str} {key} {mod_item[key]}\n")
                    f.write("\n")
        print(f"\nWARNING: Some changes failed and were written to afailed.ap")
        if not write_plan:
             return {"status": "FAILED", "error": {"code": "ALL_CHANGES_FAILED", "message": "All changes failed in force mode."}}

    if not dry_run:
        for f_path, f_content, r_path in write_plan:
            try:
                debug_print(debug, "WRITING FILE", path=f_path, content_len=len(f_content))
                os.makedirs(os.path.dirname(f_path) or '.', exist_ok=True)
                with open(f_path, 'w', encoding='utf-8', newline='' if newline_mode else None) as f: f.write(f_content)
            except IOError as e:
                err_details = {"status": "FAILED", "file_path": r_path, "error": {"code": "FILE_WRITE_ERROR", "message": str(e)}}
                if create_failure_case:
                    # We can't know which original_content this write corresponds to without more tracking.
                    # Best effort: use the last known original_content. This is an edge case.
                    create_failure_case_file("afailed.log", err_details, original_content if 'original_content' in locals() else None)
                return report_error(err_details)

    elif write_plan: debug_print(debug, "DRY RUN: SKIPPING WRITE", num_files=len(write_plan))
    else: debug_print(debug, "NO CHANGES: SKIPPING WRITE")

    return {"status": "SUCCESS"}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Apply an AI-friendly Patch (ap) file.")
    parser.add_argument("patch_file", help="Path to the .ap patch file.")
    parser.add_argument("--dir", default=".", help="The root directory of the source code.")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without modifying files.")
    parser.add_argument("-f", "--force", action="store_true", help="Force apply, skip atomicity and save failures to afailed.ap.")
    parser.add_argument("--json-report", action="store_true", help="Output machine-readable JSON on failure.")
    parser.add_argument("--failure-report", help="Path to save a detailed JSON report on failure (includes context).")
    parser.add_argument("--create-failure-case", action="store_true", help="On failure, create afailed.log (or afailed.<mod_idx>.log with --force) with full context for debugging.")
    parser.add_argument("--debug", action="store_true", help="Enable detailed debug logging.")
    parser.add_argument("-v", "--version", action="version", version="ap patcher 3.0")

    args = parser.parse_args()
    result = apply_patch(args.patch_file, args.dir, args.dry_run, args.json_report, args.debug, args.force, args.failure_report, args.create_failure_case)

    if args.json_report and result['status'] != 'SUCCESS':
        print(json.dumps(result, indent=2))

    if result["status"] != "SUCCESS":
        exit(1)