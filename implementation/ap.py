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
        try:
            anchor_pos = content.index(anchor)
            search_space, offset, anchor_found = content[anchor_pos:], anchor_pos, True
            debug_print(debug, "ANCHOR FOUND", position=anchor_pos)
        except ValueError:
            debug_print(debug, "ANCHOR NOT FOUND")
            return None, {
                "code": "ANCHOR_NOT_FOUND",
                "message": "Anchor not found.",
                "context": {
                    "anchor": anchor
                }
            }

    debug_print(debug, "SNIPPET SEARCH", snippet=snippet, search_space_len=len(search_space))
    occurrences = smart_find(search_space, snippet)

    # Heuristic: If an anchor is used, we assume the first match is the correct one.
    # This resolves ambiguities within a specific function or class.
    if anchor and len(occurrences) > 1:
        debug_print(
            debug, "AMBIGUITY HEURISTIC",
            message="Anchor present, taking first match.", all_occurrences=occurrences
        )
        occurrences = occurrences[:1]

    debug_print(debug, "SNIPPET SEARCH RESULT", num_occurrences=len(occurrences), occurrences=occurrences)

    if not occurrences:
        context = {
            "snippet": snippet,
            "anchor": anchor,
            "anchor_found": anchor_found,
            "fuzzy_matches": get_fuzzy_matches(search_space, snippet)
        }
        return None, {
            "code": "SNIPPET_NOT_FOUND",
            "message": "Snippet not found.",
            "context": context
        }
    if len(occurrences) > 1:
        context = {
            "snippet": snippet,
            "anchor": anchor,
            "anchor_found": anchor_found,
            "count": len(occurrences)
        }
        return None, {
            "code": "AMBIGUOUS_MATCH",
            "message": f"Snippet found {len(occurrences)} times.",
            "context": context
        }

    start_pos, end_pos = occurrences[0]
    return (start_pos + offset, end_pos + offset), {}

def apply_patch(
    patch_file: str, project_dir: str, dry_run: bool = False,
    json_report: bool = False, debug: bool = False
) -> Dict[str, Any]:
    def report_error(details):
        if not json_report:
            print(f"\nERROR: {details['error']['message']}")
            ctx = details['error'].get('context', {})
            if 'snippet' in ctx: print(f"---\nSnippet:\n{ctx['snippet']}\n---")
            if ctx.get('fuzzy_matches'):
                print("Did you mean one of these?")
                for match in ctx['fuzzy_matches']: print(f"  Line {match['line_number']} (Score: {match['score']}): {match['text']}")
        return details

    try:
        with open(patch_file, 'r', encoding='utf-8') as f: data = yaml.safe_load(f)
    except Exception as e:
        return report_error({
            "status": "FAILED",
            "error": {
                "code": "INVALID_PATCH_FILE",
                "message": str(e)
            }
        })

    for change in data.get('changes', []):
        relative_path = change['file_path']

        # Security check: Prevent path traversal. The final path must be within the project directory.
        real_project_dir = os.path.realpath(project_dir)
        # Construct the path and then get its real path for comparison.
        real_file_path = os.path.realpath(os.path.join(project_dir, relative_path))

        # The real path of the file must start with the real path of the project directory.
        # os.path.join is used to add a trailing separator if needed, preventing /foo/bar from matching /foo/barbaz
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

        debug_print(debug, "PROCESSING FILE", file=file_path,
                    newline_mode=newline_mode or "DETECTED", detected_newline=newline_char)

        try:
            with open(file_path, 'r', encoding='utf-8', newline=None) as f:
                original_content = f.read()
            debug_print(debug, "FILE CONTENT READ (raw)", content=original_content)
        except FileNotFoundError:
            if any(mod.get('action') == 'CREATE_FILE' for mod in change.get('modifications', [])):
                original_content = ""
                debug_print(debug, "FILE NOT FOUND (will be created)")
            else:
                return report_error({
                    "status": "FAILED",
                    "file_path": file_path,
                    "error": {
                        "code": "FILE_NOT_FOUND",
                        "message": "Target file not found."
                    }
                })

        # Normalize all line endings to LF for consistent internal processing.
        internal_newline = '\n'
        working_content = original_content.replace('\r\n', internal_newline).replace('\r', internal_newline)

        for mod_idx, mod in enumerate(change.get('modifications', [])):
            action = mod.get('action')
            debug_print(debug, f"MODIFICATION #{mod_idx}", action=action)
            if not action:
                return report_error({
                    "status": "FAILED",
                    "file_path": file_path,
                    "mod_idx": mod_idx,
                    "error": {
                        "code": "INVALID_MODIFICATION",
                        "message": "'action' is a required field."
                    }
                })

            content_to_add = mod.get('content', '')

            # Idempotency Check for CREATE_FILE
            if action == 'CREATE_FILE':
                if os.path.exists(file_path):
                    with open(file_path, 'r', encoding='utf-8', newline=None) as f_check:
                        existing_content = f_check.read().replace('\r\n', internal_newline).replace('\r', internal_newline)
                    normalized_existing = "\n".join(l.strip() for l in existing_content.strip().splitlines())
                    normalized_new = "\n".join(l.strip() for l in content_to_add.strip().splitlines())
                    if normalized_existing == normalized_new:
                        debug_print(debug, "IDEMPOTENCY SKIP", message="File already exists with matching content.", file_path=file_path)
                        working_content = existing_content # Ensure no changes are written
                        break # Skip all other modifications for this file
                working_content = content_to_add.replace('\r\n', internal_newline).replace('\r', internal_newline)
                break

            target = mod.get('target', {}); snippet = target.get('snippet', '')
            if not snippet:
                return report_error({
                    "status": "FAILED",
                    "file_path": file_path,
                    "mod_idx": mod_idx,
                    "error": {
                        "code": "INVALID_MODIFICATION",
                        "message": f"'snippet' is required for action '{action}'."
                    }
                })

            target_pos, error = find_target_in_content(working_content, target.get('anchor'), snippet, debug)

            # Idempotency Checks (when snippet is not found)
            if error and error.get('code') == 'SNIPPET_NOT_FOUND':
                if action == 'DELETE':
                    debug_print(debug, "IDEMPOTENCY SKIP", message="Snippet to delete is already gone.", snippet=snippet)
                    continue
                if action == 'REPLACE':
                    # If snippet isn't found, check if the replacement content is already there instead.
                    # We turn off debug for this sub-search to avoid confusing logs.
                    content_pos, _ = find_target_in_content(working_content, target.get('anchor'), content_to_add, debug=False)
                    if content_pos:
                        debug_print(debug, "IDEMPOTENCY SKIP", message="REPLACE snippet not found, but replacement content exists.", snippet=snippet)
                        continue

            if error:
                report = {"status": "FAILED", "file_path": file_path, "mod_idx": mod_idx, "error": error}
                report['error']['context']['action'] = action
                return report_error(report)

            start_pos, end_pos = target_pos

            debug_print(debug, "TARGET FOUND", start_pos=start_pos, end_pos=end_pos,
                        found_text=working_content[start_pos:end_pos])

            # Expand selection to include surrounding blank lines if requested.
            leading_blanks_to_include = target.get('include_leading_blank_lines', 0)
            if leading_blanks_to_include > 0:
                expanded_start = start_pos
                for _ in range(leading_blanks_to_include):
                    line_start_idx = working_content.rfind(internal_newline, 0, expanded_start -1)
                    if line_start_idx == -1: # Beginning of file
                        if working_content[:expanded_start].strip() == "": expanded_start = 0
                        break
                    prev_line = working_content[line_start_idx+1:expanded_start]
                    if prev_line.strip() == "": expanded_start = line_start_idx + 1
                    else: break
                start_pos = expanded_start

            trailing_blanks_to_include = target.get('include_trailing_blank_lines', 0)
            if trailing_blanks_to_include > 0:
                current_pos = end_pos
                for _ in range(trailing_blanks_to_include):
                    # Find the end of the next line
                    next_newline_pos = working_content.find(internal_newline, current_pos)

                    if next_newline_pos == -1:
                        # This is the last line in the file. Check if it's blank.
                        if working_content[current_pos:].strip() == "":
                            end_pos = len(working_content)
                        break # No more lines to check

                    line_content = working_content[current_pos:next_newline_pos]
                    if line_content.strip() == "":
                        # The line is blank, expand selection to include its newline
                        end_pos = next_newline_pos + 1
                        current_pos = end_pos
                    else:
                        # Next line is not blank, so we stop.
                        break

            # Idempotency Checks (when snippet is found)
            def normalize_block(text): return "\n".join(line.strip() for line in text.strip().splitlines())

            if action == 'REPLACE':
                # If the existing block already matches the content, skip.
                if normalize_block(working_content[start_pos:end_pos]) == normalize_block(content_to_add):
                    debug_print(debug, "IDEMPOTENCY SKIP", message="REPLACE content already present.")
                    continue
            elif action == 'INSERT_AFTER':
                # If the content to add is already present right after the snippet, skip.
                next_chunk = working_content[end_pos:]
                if normalize_block(next_chunk).startswith(normalize_block(content_to_add)):
                     debug_print(debug, "IDEMPOTENCY SKIP", message="INSERT_AFTER content already present.")
                     continue
            elif action == 'INSERT_BEFORE':
                # If the content to add is already present right before the snippet, skip.
                prev_chunk = working_content[:start_pos]
                if normalize_block(prev_chunk).endswith(normalize_block(content_to_add)):
                    debug_print(debug, "IDEMPOTENCY SKIP", message="INSERT_BEFORE content already present.")
                    continue

            if action == 'DELETE':
                working_content = working_content[:start_pos] + working_content[end_pos:]
                continue
            debug_print(debug, "TARGET FOUND", start_pos=start_pos, end_pos=end_pos,
                        found_text=working_content[start_pos:end_pos])

            # Expand selection to include surrounding blank lines if requested.
            leading_blanks_to_include = target.get('include_leading_blank_lines', 0)
            if leading_blanks_to_include > 0:
                expanded_start = start_pos
                for _ in range(leading_blanks_to_include):
                    line_start_idx = working_content.rfind(internal_newline, 0, expanded_start -1)
                    if line_start_idx == -1: # Beginning of file
                        if working_content[:expanded_start].strip() == "": expanded_start = 0
                        break
                    prev_line = working_content[line_start_idx+1:expanded_start]
                    if prev_line.strip() == "": expanded_start = line_start_idx + 1
                    else: break
                start_pos = expanded_start

            trailing_blanks_to_include = target.get('include_trailing_blank_lines', 0)
            if trailing_blanks_to_include > 0:
                expanded_end = end_pos
                for _ in range(trailing_blanks_to_include):
                    line_end_idx = working_content.find(internal_newline, expanded_end)
                    if line_end_idx == -1: # End of file
                        if working_content[expanded_end:].strip() == "": expanded_end = len(working_content)
                        break
                    next_line = working_content[expanded_end:line_end_idx]
                    if next_line.strip() == "": expanded_end = line_end_idx + 1
                    else: break
                end_pos = expanded_end

            if action == 'DELETE':
                working_content = working_content[:start_pos] + working_content[end_pos:]
                continue

            first_char_pos = start_pos
            while first_char_pos < len(working_content) and working_content[first_char_pos].isspace():
                first_char_pos += 1
            line_start_idx = working_content.rfind(internal_newline, 0, first_char_pos) + 1
            indentation = working_content[line_start_idx:first_char_pos]

            indented_content = internal_newline.join(indentation + line for line in content_to_add.splitlines())

            before_block = working_content[:start_pos]
            original_block = working_content[start_pos:end_pos]
            after_block = working_content[end_pos:]

            # Ensure the new block ends with a newline to maintain structure.
            if indented_content and not indented_content.endswith(internal_newline):
                indented_content += internal_newline

            if action == 'REPLACE':
                working_content = before_block + indented_content + after_block
            elif action == 'INSERT_AFTER':
                working_content = before_block + original_block + indented_content + after_block
            elif action == 'INSERT_BEFORE':
                working_content = before_block + indented_content + original_block + after_block

        # Post-processing: strip trailing whitespace from all lines.
        lines = working_content.split(internal_newline)
        stripped_lines = [line.rstrip(' \t') for line in lines]

        # Convert line endings back to the original/specified format before writing.
        final_content = newline_char.join(stripped_lines)

        if not dry_run and final_content != original_content:
            debug_print(debug, "WRITING FILE", path=file_path, content=final_content)
            os.makedirs(os.path.dirname(file_path) or '.', exist_ok=True)
            with open(file_path, 'w', encoding='utf-8', newline='') as f:
                f.write(final_content)
        elif dry_run: debug_print(debug, "DRY RUN: SKIPPING WRITE")
        else: debug_print(debug, "NO CHANGES: SKIPPING WRITE")

    return {"status": "SUCCESS"}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Apply an AI-friendly Patch (ap) file.")
    parser.add_argument("--patch", required=True, help="Path to the .ap patch file.")
    parser.add_argument("--dir", default=".", help="The root directory of the source code.")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without modifying files.")
    parser.add_argument("--json-report", action="store_true", help="Output machine-readable JSON on failure.")
    parser.add_argument("--debug", action="store_true", help="Enable detailed debug logging.")

    args = parser.parse_args()
    result = apply_patch(args.patch, args.dir, args.dry_run, args.json_report, args.debug)

    if args.json_report and result['status'] != 'SUCCESS':
        print(json.dumps(result, indent=2))

    if result["status"] != "SUCCESS":
        exit(1)