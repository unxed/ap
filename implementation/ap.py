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

    header_pattern = re.compile(r'^([a-f0-9]{8})\s+AP\s+3\.0$')
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
                if reading_key == "path" and current_file_change: current_file_change['file_path'] = value
                elif current_modification: current_modification[reading_key] = value
                reading_key, value_lines = None, []

            parts = match.group(1).strip().split(maxsplit=1)
            key, args = parts[0], parts[1] if len(parts) > 1 else None

            ACTIONS = {'REPLACE', 'INSERT_AFTER', 'INSERT_BEFORE', 'DELETE', 'CREATE_FILE'}
            VALUE_KEYS = {'snippet', 'anchor', 'content', 'start_snippet', 'end_snippet'}
            ARG_KEYS = {'include_leading_blank_lines', 'include_trailing_blank_lines'}
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
        if reading_key == "path" and current_file_change: current_file_change['file_path'] = value
        elif current_modification: current_modification[reading_key] = value

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
    matches = []
    if not snippet or not snippet.strip(): return []
    snippet_first_line = snippet.strip().splitlines()[0]
    for i, line in enumerate(content.splitlines()):
        line = line.strip()
        if not line: continue
        ratio = difflib.SequenceMatcher(None, snippet_first_line, line).ratio()
        if ratio >= cutoff:
            matches.append({"line_number": i + 1, "score": round(ratio, 2), "text": line})
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
        if [line.strip() for line in content_lines_found] == normalized_snippet_lines:
            start_pos = len("".join(original_lines[:i]))
            end_pos = len("".join(original_lines[:end_line_index + 1]))
            occurrences.append((start_pos, end_pos))
    return occurrences

def find_target_in_content(content: str, anchor: Optional[str], snippet: str, debug: bool = False) -> Tuple[Optional[Tuple[int, int]], Dict[str, Any]]:
    search_space, offset, anchor_found = content, 0, None
    if anchor:
        debug_print(debug, "ANCHOR SEARCH", anchor=anchor)
        anchor_occurrences = smart_find(content, anchor)
        if not anchor_occurrences: return None, {"code": "ANCHOR_NOT_FOUND", "message": "Anchor not found.", "context": {"anchor": anchor}}
        if len(anchor_occurrences) > 1: return None, {"code": "AMBIGUOUS_ANCHOR", "message": f"Anchor found {len(anchor_occurrences)} times.", "context": {"anchor": anchor, "count": len(anchor_occurrences)}}
        anchor_start, anchor_end = anchor_occurrences[0]
        search_space, offset, anchor_found = content[anchor_end:], anchor_end, True
        debug_print(debug, "ANCHOR FOUND", position=anchor_start, search_offset=offset)

    debug_print(debug, "SNIPPET SEARCH", snippet=snippet, search_space_len=len(search_space))
    occurrences = smart_find(search_space, snippet)
    debug_print(debug, "SNIPPET SEARCH RESULT", num_found=len(occurrences))
    if not occurrences:
        context = {"snippet": snippet, "anchor": anchor, "anchor_found": anchor_found, "fuzzy_matches": get_fuzzy_matches(content, snippet)}
        return None, {"code": "SNIPPET_NOT_FOUND", "message": "Snippet not found.", "context": context}
    if len(occurrences) > 1 and not anchor: return None, {"code": "AMBIGUOUS_MATCH", "message": f"Snippet found {len(occurrences)} times.", "context": {"snippet": snippet, "count": len(occurrences)}}
    start_pos, end_pos = occurrences[0]
    return (start_pos + offset, end_pos + offset), {}

def apply_patch(patch_file: str, project_dir: str, dry_run: bool = False, json_report: bool = False, debug: bool = False, force: bool = False) -> Dict[str, Any]:
    def report_error(details):
        if not json_report:
            file_info = f" in file '{details.get('file_path')}'" if details.get('file_path') else ""
            mod_info = f" (modification #{details['mod_idx'] + 1})" if 'mod_idx' in details else ""
            print(f"\nERROR{file_info}{mod_info}: {details['error']['message']}")
            ctx = details['error'].get('context', {})
            def print_snippet(name, value):
                print(f"  {name}:")
                for line in (value or "").strip().splitlines(): print(f"    {line}")
            for key in ['anchor', 'snippet', 'start_snippet', 'end_snippet']:
                if ctx.get(key): print_snippet(key.replace('_', ' ').title(), ctx[key])
            if ctx.get('fuzzy_matches'):
                print("  Did you mean one of these?")
                for match in ctx['fuzzy_matches']: print(f"    Line {match['line_number']} (Score: {match['score']}): {match['text']}")
        return details

    if force and os.path.exists("afailed.ap"):
        err_msg = "afailed.ap exists. Please remove or rename it before running with --force."
        if json_report: return {"status": "FAILED", "error": {"code": "AFAILED_EXISTS", "message": err_msg}}
        print(f"ERROR: {err_msg}")
        exit(1)

    patch_id_str = "00000000"
    try:
        with open(patch_file, 'r', encoding='utf-8') as f:
            for line in f:
                match = re.match(r'^([a-f0-9]{8})\s+AP\s+3\.0$', line.strip())
                if match:
                    patch_id_str = match.group(1)
                    break
    except FileNotFoundError:
        pass # This will be handled properly by the main parse function
    failed_changes_output = []
    try: data = parse_ap3_format(patch_file)
    except (ValueError, FileNotFoundError) as e:
        return report_error({"status": "FAILED", "error": { "code": "INVALID_PATCH_FILE", "message": str(e) }})

    write_plan = []
    for change in data.get('changes', []):
        if 'file_path' not in change: return report_error({"status": "FAILED", "error": {"code": "INVALID_PATCH_FILE", "message": "Missing 'file_path' for a change block."}})
        relative_path = change['file_path']

        real_project_dir = os.path.realpath(project_dir)
        real_file_path = os.path.realpath(os.path.join(project_dir, relative_path))
        if not real_file_path.startswith(os.path.join(real_project_dir, '')):
            return report_error({"status": "FAILED", "file_path": relative_path, "error": {"code": "INVALID_FILE_PATH", "message": "Path traversal detected."}})

        file_path = os.path.join(project_dir, relative_path)
        newline_mode = change.get('newline')
        newline_char = {'LF': '\n', 'CRLF': '\r\n', 'CR': '\r'}.get(newline_mode) or (detect_line_endings(file_path) if os.path.exists(file_path) else os.linesep)
        debug_print(debug, "PLANNING FOR FILE", file=file_path, newline_mode=newline_mode or "DETECTED", detected_newline=newline_char)

        try:
            with open(file_path, 'r', encoding='utf-8', newline=None) as f: original_content = f.read()
        except FileNotFoundError:
            if any(mod.get('action') == 'CREATE_FILE' for mod in change.get('modifications', [])): original_content = ""
            else: return report_error({"status": "FAILED", "file_path": relative_path, "error": { "code": "FILE_NOT_FOUND", "message": "Target file not found." }})

        internal_newline = '\n'
        working_content = original_content.replace('\r\n', internal_newline).replace('\r', internal_newline)

        for mod_idx, mod in enumerate(change.get('modifications', [])):
            action = mod.get('action')
            debug_print(debug, f"MODIFICATION #{mod_idx+1}", action=action)
            if not action: return report_error({"status": "FAILED", "file_path": relative_path, "mod_idx": mod_idx, "error": {"code": "INVALID_MODIFICATION", "message": "'action' is required."}})

            content_to_add = mod.get('content', '')
            if action == 'CREATE_FILE':
                if os.path.exists(file_path):
                    with open(file_path, 'r', encoding='utf-8', newline=None) as f_check:
                        existing_content = f_check.read().replace('\r\n', internal_newline).replace('\r', internal_newline)
                    normalized_existing = "\n".join(l.strip() for l in existing_content.strip().splitlines())
                    normalized_new = "\n".join(l.strip() for l in (content_to_add or "").strip().splitlines())
                    if normalized_existing == normalized_new:
                        debug_print(debug, "IDEMPOTENCY SKIP", message="File exists with matching content.", file_path=file_path)
                        break
                working_content = (content_to_add or "").replace('\r\n', internal_newline).replace('\r', internal_newline)
                break

            snippet, start_snippet, end_snippet = mod.get('snippet'), mod.get('start_snippet'), mod.get('end_snippet')
            target_pos, error = None, {}

            if snippet is not None:
                if start_snippet is not None or end_snippet is not None: return report_error({"status": "FAILED", "file_path": relative_path, "mod_idx": mod_idx, "error": {"code": "INVALID_MODIFICATION", "message": "Cannot use 'snippet' with range snippets."}})
                target_pos, error = find_target_in_content(working_content, mod.get('anchor'), snippet, debug)
            elif start_snippet is not None and end_snippet is not None:
                if action not in ['REPLACE', 'DELETE']: return report_error({"status": "FAILED", "file_path": relative_path, "mod_idx": mod_idx, "error": {"code": "INVALID_MODIFICATION", "message": f"Action '{action}' does not support range."}})
                start_pos_info, error = find_target_in_content(working_content, mod.get('anchor'), start_snippet, debug)
                if not error:
                    start_range_begin, start_range_end = start_pos_info
                    end_occurrences = smart_find(working_content[start_range_end:], end_snippet)
                    if not end_occurrences: error = {"code": "END_SNIPPET_NOT_FOUND", "message": "End snippet not found.", "context": {"start_snippet": start_snippet, "end_snippet": end_snippet}}
                    else:
                        end_range_begin_rel, end_range_end_rel = end_occurrences[0]
                        target_pos = (start_range_begin, start_range_end + end_range_end_rel)
            elif action != 'CREATE_FILE': return report_error({"status": "FAILED", "file_path": relative_path, "mod_idx": mod_idx, "error": {"code": "INVALID_MODIFICATION", "message": "Modification requires locators."}})

            if error:
                is_idempotency_skip = False
                error_codes = ['SNIPPET_NOT_FOUND', 'ANCHOR_NOT_FOUND', 'END_SNIPPET_NOT_FOUND']
                if action == 'DELETE' and error['code'] in error_codes:
                    debug_print(debug, "IDEMPOTENCY SKIP", message="Snippet to delete is already gone.", snippet=snippet or start_snippet); is_idempotency_skip = True
                if action == 'REPLACE' and error['code'] in error_codes:
                    content_pos, _ = find_target_in_content(working_content, mod.get('anchor'), content_to_add or "", debug=False)
                    if content_pos: debug_print(debug, "IDEMPOTENCY SKIP", message="Snippet not found, but replacement content exists.", snippet=snippet or start_snippet); is_idempotency_skip = True
                if is_idempotency_skip: continue

                if force:
                    print(f"  - FAILED: Mod #{mod_idx + 1} ({mod.get('action')}) in '{relative_path}'. Reason: {error.get('message')}")
                    failed_file_block = next((item for item in failed_changes_output if item.get('file_path') == relative_path), None)
                    if not failed_file_block:
                        failed_file_block = {'file_path': relative_path, 'modifications': []}
                        if change.get('newline'): failed_file_block['newline'] = change.get('newline')
                        failed_changes_output.append(failed_file_block)
                    failed_file_block['modifications'].append(mod)
                    continue

                report = {"status": "FAILED", "file_path": relative_path, "mod_idx": mod_idx, "error": error}
                report['error']['context']['action'] = action
                return report_error(report)

            if action == 'CREATE_FILE': continue
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

            first_char_pos = start_pos
            while first_char_pos < len(working_content) and working_content[first_char_pos] in ' \t': first_char_pos += 1
            line_start_idx = working_content.rfind(internal_newline, 0, first_char_pos) + 1
            indentation = ""; # indentation = working_content[line_start_idx:first_char_pos]

            indented_content = ""
            if content_to_add:
                content_lines = content_to_add.splitlines()
                indented_content = internal_newline.join(indentation + line for line in content_lines)
                # Ensure trailing newline for inserts or if replacing a block that had one
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

        if final_content != original_content:
            write_plan.append((file_path, final_content, relative_path))

    if force and failed_changes_output:
        with open("afailed.ap", "w", encoding="utf-8") as f:
            f.write(f"# Summary: Failed changes from a forced patch application.\n\n")
            f.write(f"{patch_id_str} AP 3.0\n\n")
            for change_item in failed_changes_output:
                f.write(f"{patch_id_str} FILE")
                if change_item.get("newline"):
                    f.write(f" {change_item['newline']}")
                f.write(f"\n{change_item['file_path']}\n\n")
                for mod_item in change_item['modifications']:
                    f.write(f"{patch_id_str} {mod_item['action']}\n")
                    for key in ['anchor', 'snippet', 'start_snippet', 'end_snippet', 'content']:
                        if key in mod_item:
                            f.write(f"{patch_id_str} {key}\n{mod_item[key]}\n")
                    for key in ['include_leading_blank_lines', 'include_trailing_blank_lines']:
                        if key in mod_item:
                            f.write(f"{patch_id_str} {key} {mod_item[key]}\n")
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
            except IOError as e: return report_error({"status": "FAILED", "file_path": r_path, "error": {"code": "FILE_WRITE_ERROR", "message": str(e)}})
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
    parser.add_argument("--debug", action="store_true", help="Enable detailed debug logging.")
    parser.add_argument("-v", "--version", action="version", version="ap patcher 3.0")

    args = parser.parse_args()
    result = apply_patch(args.patch_file, args.dir, args.dry_run, args.json_report, args.debug, args.force)

    if args.json_report and result['status'] != 'SUCCESS':
        print(json.dumps(result, indent=2))

    if result["status"] != "SUCCESS":
        exit(1)