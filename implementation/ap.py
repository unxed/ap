#!/usr/bin/env python3
import yaml
import os
import argparse
import difflib
import json
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

def detect_line_endings(file_path: str) -> str:
    """Detects the dominant line ending character in a file."""
    try:
        with open(file_path, 'rb') as f:
            chunk = f.read(1024)
            if b'\r\n' in chunk: return '\r\n'
            if b'\n' in chunk: return '\n'
            if b'\r' in chunk: return '\r'
    except (IOError, FileNotFoundError): pass
    return os.linesep

def get_fuzzy_matches(content: str, snippet: str, cutoff: float = 0.7) -> List[Dict[str, Any]]:
    """Finds lines in content that are similar to the first line of the snippet."""
    matches = []
    if not snippet.strip(): return []
    snippet_first_line = snippet.strip().splitlines()[0]
    for i, line in enumerate(content.splitlines()):
        line = line.strip()
        if not line: continue
        ratio = difflib.SequenceMatcher(None, snippet_first_line, line).ratio()
        if ratio >= cutoff:
            matches.append({"line_number": i + 1, "score": round(ratio, 2), "text": line})
    return sorted(matches, key=lambda x: x['score'], reverse=True)[:3]

def smart_find(content: str, snippet: str) -> List[Tuple[int, int]]:
    """Finds all occurrences of a snippet, ignoring indentation and blank lines."""
    original_lines = content.splitlines(keepends=True)
    snippet_lines = [line for line in snippet.strip().splitlines() if line.strip()]
    normalized_snippet_lines = [line.strip() for line in snippet_lines]
    if not snippet_lines: return []

    occurrences = []
    for i in range(len(original_lines)):
        # A match must start on a non-blank line
        if not original_lines[i].strip():
            continue

        content_lines_found = []
        end_line_index = i - 1 # Will be updated in the loop

        # Scan forward from line i to find a potential match
        temp_j = i
        while len(content_lines_found) < len(snippet_lines) and temp_j < len(original_lines):
            line = original_lines[temp_j]
            if line.strip():
                content_lines_found.append(line)
            end_line_index = temp_j
            temp_j += 1

        if [line.strip() for line in content_lines_found] == normalized_snippet_lines:
            start_pos = len("".join(original_lines[:i]))
            end_pos = len("".join(original_lines[:end_line_index + 1]))
            occurrences.append((start_pos, end_pos))

    return occurrences

def find_target_in_content(
    content: str, anchor: Optional[str], snippet: str, debug: bool = False
) -> Tuple[Optional[Tuple[int, int]], Dict[str, Any]]:
    search_space, offset, anchor_found = content, 0, None
    if anchor:
        debug_print(debug, "ANCHOR SEARCH", anchor=anchor)
        anchor_occurrences = smart_find(content, anchor)

        if not anchor_occurrences:
            debug_print(debug, "ANCHOR NOT FOUND")
            return None, {"code": "ANCHOR_NOT_FOUND", "message": "Anchor not found.", "context": {"anchor": anchor}}

        if len(anchor_occurrences) > 1:
            return None, {
                "code": "AMBIGUOUS_ANCHOR",
                "message": f"Anchor found {len(anchor_occurrences)} times, must be unique.",
                "context": {"anchor": anchor, "count": len(anchor_occurrences)}}

        anchor_start, anchor_end = anchor_occurrences[0]
        search_space, offset, anchor_found = content[anchor_end:], anchor_end, True
        debug_print(debug, "ANCHOR FOUND", position=anchor_start, search_offset=offset)

    debug_print(debug, "SNIPPET SEARCH", snippet=snippet, search_space_len=len(search_space))
    occurrences = smart_find(search_space, snippet)
    debug_print(debug, "SNIPPET SEARCH RESULT", num_found=len(occurrences))

    if not occurrences:
        context = {"snippet": snippet, "anchor": anchor, "anchor_found": anchor_found}
        context["fuzzy_matches"] = get_fuzzy_matches(search_space, snippet)
        message, code = "Snippet not found.", "SNIPPET_NOT_FOUND"
        return None, {"code": code, "message": message, "context": context}

    if len(occurrences) > 1 and not anchor:
        return None, {
            "code": "AMBIGUOUS_MATCH",
            "message": f"Snippet found {len(occurrences)} times. Use an 'anchor' to disambiguate.",
            "context": {"snippet": snippet, "anchor": anchor, "count": len(occurrences)}
        }

    start_pos, end_pos = occurrences[0]
    return (start_pos + offset, end_pos + offset), {}

def apply_patch(
    patch_file: str, project_dir: str, dry_run: bool = False,
    json_report: bool = False, debug: bool = False
) -> Dict[str, Any]:
    def report_error(details):
        if not json_report:
            file_info = f" in file '{details.get('file_path')}'" if details.get('file_path') else ""
            mod_info = ""
            if 'mod_idx' in details:
                mod_info = f" (modification #{details['mod_idx'] + 1})"

            print(f"\nERROR{file_info}{mod_info}: {details['error']['message']}")
            ctx = details['error'].get('context', {})

            def print_snippet(name, value):
                print(f"  {name}:")
                for line in value.strip().splitlines():
                    print(f"    {line}")

            if ctx.get('anchor'): print_snippet("Anchor", ctx['anchor'])
            if ctx.get('snippet'): print_snippet("Snippet", ctx['snippet'])
            if ctx.get('start_snippet'): print_snippet("Start Snippet", ctx['start_snippet'])
            if ctx.get('end_snippet'): print_snippet("End Snippet", ctx['end_snippet'])

            if ctx.get('fuzzy_matches'):
                print("  Did you mean one of these?")
                for match in ctx['fuzzy_matches']:
                    print(f"    Line {match['line_number']} (Score: {match['score']}): {match['text']}")
        return details

    try:
        with open(patch_file, 'r', encoding='utf-8') as f: data = yaml.safe_load(f)
    except Exception as e:
        return report_error({
            "status": "FAILED",
            "error": { "code": "INVALID_PATCH_FILE", "message": str(e) }
        })

    write_plan = []
    # --- PHASE 1: VALIDATE AND PREPARE ALL CHANGES IN MEMORY ---
    for change in data.get('changes', []):
        relative_path = change['file_path']

        real_project_dir = os.path.realpath(project_dir)
        real_file_path = os.path.realpath(os.path.join(project_dir, relative_path))
        if not real_file_path.startswith(os.path.join(real_project_dir, '')):
            return report_error({
                "status": "FAILED", "file_path": relative_path,
                "error": {
                    "code": "INVALID_FILE_PATH",
                    "message": "Path traversal detected. File path must be relative and stay within the project directory."
                }})

        file_path = os.path.join(project_dir, relative_path)
        newline_mode = change.get('newline')
        newline_char = {'LF': '\n', 'CRLF': '\r\n', 'CR': '\r'}.get(newline_mode) or \
                       (detect_line_endings(file_path) if os.path.exists(file_path) else os.linesep)

        debug_print(debug, "PLANNING FOR FILE", file=file_path,
                    newline_mode=newline_mode or "DETECTED", detected_newline=newline_char)

        try:
            with open(file_path, 'r', encoding='utf-8', newline=None) as f: original_content = f.read()
        except FileNotFoundError:
            if any(mod.get('action') == 'CREATE_FILE' for mod in change.get('modifications', [])):
                original_content = ""
            else:
                return report_error({
                    "status": "FAILED", "file_path": relative_path,
                    "error": { "code": "FILE_NOT_FOUND", "message": "Target file not found." }
                })

        internal_newline = '\n'
        working_content = original_content.replace('\r\n', internal_newline).replace('\r', internal_newline)

        for mod_idx, mod in enumerate(change.get('modifications', [])):
            action = mod.get('action')
            debug_print(debug, f"MODIFICATION #{mod_idx}", action=action)
            if not action:
                return report_error({
                    "status": "FAILED",
                    "file_path": relative_path,
                    "mod_idx": mod_idx,
                    "error": {
                        "code": "INVALID_MODIFICATION",
                        "message": "'action' is a required field."
                    }
                })

            content_to_add = mod.get('content', '')
            if action == 'CREATE_FILE':
                if os.path.exists(file_path):
                    with open(file_path, 'r', encoding='utf-8', newline=None) as f_check:
                        existing_content = f_check.read() \
                            .replace('\r\n', internal_newline) \
                            .replace('\r', internal_newline)
                    normalized_existing = "\n".join(l.strip() for l in existing_content.strip().splitlines())
                    normalized_new = "\n".join(l.strip() for l in content_to_add.strip().splitlines())
                    if normalized_existing == normalized_new:
                        debug_print(debug, "IDEMPOTENCY SKIP", message="File already exists with matching content.", file_path=file_path)
                        working_content = existing_content
                        break
                working_content = content_to_add.replace('\r\n', internal_newline).replace('\r', internal_newline)
                break

            snippet = mod.get('snippet')
            start_snippet, end_snippet = mod.get('start_snippet'), mod.get('end_snippet')
            target_pos, error = None, {}

            if snippet is not None:
                if start_snippet is not None or end_snippet is not None:
                    return report_error({"status": "FAILED", "file_path": relative_path, "mod_idx": mod_idx, "error": {"code": "INVALID_MODIFICATION", "message": "Cannot use 'snippet' with 'start_snippet' or 'end_snippet'."}})
                target_pos, error = find_target_in_content(working_content, mod.get('anchor'), snippet, debug)
            elif start_snippet is not None and end_snippet is not None:
                if action not in ['REPLACE', 'DELETE']:
                    return report_error({"status": "FAILED", "file_path": relative_path, "mod_idx": mod_idx, "error": {"code": "INVALID_MODIFICATION", "message": f"Action '{action}' does not support range-based modification."}})

                start_pos_info, error = find_target_in_content(working_content, mod.get('anchor'), start_snippet, debug)
                if not error:
                    start_range_begin, start_range_end = start_pos_info
                    end_occurrences = smart_find(working_content[start_range_end:], end_snippet)
                    if not end_occurrences:
                        error = {"code": "END_SNIPPET_NOT_FOUND", "message": "End snippet not found after start snippet.", "context": {"start_snippet": start_snippet, "end_snippet": end_snippet}}
                    else:
                        end_range_begin_rel, end_range_end_rel = end_occurrences[0]
                        final_start_pos = start_range_begin
                        final_end_pos = start_range_end + end_range_end_rel
                        target_pos = (final_start_pos, final_end_pos)
            else:
                return report_error({"status": "FAILED", "file_path": relative_path, "mod_idx": mod_idx, "error": {"code": "INVALID_MODIFICATION", "message": f"Modification must contain either 'snippet' or both 'start_snippet' and 'end_snippet'."}})

            if error and error.get('code') == 'SNIPPET_NOT_FOUND':
                if action == 'DELETE':
                    debug_print(debug, "IDEMPOTENCY SKIP", message="Snippet to delete is already gone.", snippet=snippet)
                    continue
                if action == 'REPLACE':
                    content_pos, _ = find_target_in_content(working_content, mod.get('anchor'), content_to_add, debug=False)
                    if content_pos:
                        debug_print(debug, "IDEMPOTENCY SKIP", message="REPLACE snippet not found, but replacement content exists.", snippet=snippet)
                        continue
            if error:
                report = {"status": "FAILED", "file_path": relative_path, "mod_idx": mod_idx, "error": error}
                report['error']['context']['action'] = action
                return report_error(report)

            start_pos, end_pos = target_pos
            leading_blanks_to_include = mod.get('include_leading_blank_lines', 0)
            if leading_blanks_to_include > 0:
                expanded_start = start_pos
                for _ in range(leading_blanks_to_include):
                    line_start_idx = working_content.rfind(internal_newline, 0, expanded_start -1)
                    if line_start_idx == -1:
                        if working_content[:expanded_start].strip() == "": expanded_start = 0
                        break
                    prev_line = working_content[line_start_idx+1:expanded_start]
                    if prev_line.strip() == "": expanded_start = line_start_idx + 1
                    else: break
                start_pos = expanded_start
            trailing_blanks_to_include = mod.get('include_trailing_blank_lines', 0)
            if trailing_blanks_to_include > 0:
                expanded_end = end_pos
                for _ in range(trailing_blanks_to_include):
                    line_end_idx = working_content.find(internal_newline, expanded_end)
                    if line_end_idx == -1:
                        if working_content[expanded_end:].strip() == "": expanded_end = len(working_content)
                        break
                    next_line = working_content[expanded_end:line_end_idx]
                    if next_line.strip() == "": expanded_end = line_end_idx + 1
                    else: break
                end_pos = expanded_end

            def normalize_block(text): return "\n".join(line.strip() for line in text.strip().splitlines())
            if action == 'REPLACE':
                if normalize_block(working_content[start_pos:end_pos]) == normalize_block(content_to_add):
                    debug_print(debug, "IDEMPOTENCY SKIP", message="REPLACE content already present."); continue
            elif action == 'INSERT_AFTER':
                if normalize_block(working_content[end_pos:]).startswith(normalize_block(content_to_add)):
                     debug_print(debug, "IDEMPOTENCY SKIP", message="INSERT_AFTER content already present."); continue
            elif action == 'INSERT_BEFORE':
                if normalize_block(working_content[:start_pos]).endswith(normalize_block(content_to_add)):
                    debug_print(debug, "IDEMPOTENCY SKIP", message="INSERT_BEFORE content already present."); continue

            if action == 'DELETE':
                working_content = working_content[:start_pos] + working_content[end_pos:]
                continue

            first_char_pos = start_pos
            while first_char_pos < len(working_content) and working_content[first_char_pos].isspace(): first_char_pos += 1
            line_start_idx = working_content.rfind(internal_newline, 0, first_char_pos) + 1
            indentation = working_content[line_start_idx:first_char_pos]
            indented_content = internal_newline.join(indentation + line for line in content_to_add.splitlines())
            if indented_content and not indented_content.endswith(internal_newline): indented_content += internal_newline

            if action == 'REPLACE':
                working_content = working_content[:start_pos] + indented_content + working_content[end_pos:]
            elif action == 'INSERT_AFTER':
                working_content = working_content[:end_pos] + indented_content + working_content[end_pos:]
            elif action == 'INSERT_BEFORE':
                working_content = working_content[:start_pos] + indented_content + working_content[start_pos:]

        final_content = newline_char.join([line.rstrip(' \t') for line in working_content.split(internal_newline)])
        if final_content != original_content:
            write_plan.append((file_path, final_content, relative_path))

    # --- PHASE 2: EXECUTE ALL PLANNED WRITES ---
    if not dry_run:
        for f_path, f_content, r_path in write_plan:
            try:
                debug_print(debug, "WRITING FILE", path=f_path, content_len=len(f_content))
                os.makedirs(os.path.dirname(f_path) or '.', exist_ok=True)
                with open(f_path, 'w', encoding='utf-8', newline='') as f: f.write(f_content)
            except IOError as e:
                return report_error({"status": "FAILED", "file_path": r_path, "error": {"code": "FILE_WRITE_ERROR", "message": str(e)}})
    elif write_plan:
         debug_print(debug, "DRY RUN: SKIPPING WRITE", num_files=len(write_plan))
    else:
         debug_print(debug, "NO CHANGES: SKIPPING WRITE")

    return {"status": "SUCCESS"}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Apply an AI-friendly Patch (ap) file.")
    parser.add_argument("patch_file", help="Path to the .ap patch file.")
    parser.add_argument("--dir", default=".", help="The root directory of the source code.")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without modifying files.")
    parser.add_argument("--json-report", action="store_true", help="Output machine-readable JSON on failure.")
    parser.add_argument("--debug", action="store_true", help="Enable detailed debug logging.")

    args = parser.parse_args()
    result = apply_patch(args.patch_file, args.dir, args.dry_run, args.json_report, args.debug)

    if args.json_report and result['status'] != 'SUCCESS':
        print(json.dumps(result, indent=2))

    if result["status"] != "SUCCESS":
        exit(1)