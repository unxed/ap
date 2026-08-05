#!/usr/bin/env python3
import os
import argparse
import difflib
import json
import re
from typing import Optional, Tuple, List, Dict, Any
import shutil
try:
    from typing import TypedDict
except ImportError:
    from typing_extensions import TypedDict

# Define types for the internal patch structure for clarity and static analysis.
class Modification(TypedDict, total=False):
    action: str
    snippet: str
    anchor: str
    content: str
    snippet_tail: str
    include_leading_blank_lines: int
    include_trailing_blank_lines: int

class FileChange(TypedDict, total=False):
    file_path: str
    rename_to: str
    delete_file: bool
    newline: str
    modifications: List[Modification]

class PatchData(TypedDict):
    version: str
    patch_id: Optional[str]
    changes: List[FileChange]

def clean_lines(s: Optional[str]) -> Optional[str]:
    """Removes trailing whitespace from each line of the input string."""
    if s is None: return None
    return '\n'.join(line.rstrip(' \t') for line in s.splitlines())
def normalize_block(text: Optional[str]) -> str:
    """Normalizes a block of text the same way the search algorithm does."""
    return "\n".join(l.strip() for l in (text or "").strip().splitlines() if l.strip())

def leading_whitespace(line: str) -> str:
    return line[:len(line) - len(line.lstrip(' \t'))]

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

AP_FORMAT_VERSION = "3.2"
AP_SUPPORTED_VERSIONS = ("3.0", "3.1", "3.2")

# Canonical directive keywords of the format.
ACTION_KEYS = {'REPLACE', 'INSERT_AFTER', 'INSERT_BEFORE', 'DELETE', 'RECREATE'}
VALUE_KEYS = {'snippet', 'anchor', 'content', 'snippet_tail'}
ARG_KEYS = {'include_leading_blank_lines', 'include_trailing_blank_lines'}
NEWLINE_VALS = {'LF', 'CRLF', 'CR'}
CANONICAL_KEYS = ACTION_KEYS | VALUE_KEYS | ARG_KEYS | {'FILE', 'CREATE', 'RENAME', 'END'}

# Tolerated misspellings/synonyms that weaker models invent. Resolving them is
# safe because directive lines are always prefixed with the patch ID, so they
# can never collide with the payload.
KEY_ALIASES = {
    'CREATE_FILE': 'CREATE', 'CREATE_DIR': 'CREATE', 'NEW_FILE': 'CREATE', 'ADD_FILE': 'CREATE',
    'MOVE': 'RENAME', 'RENAME_TO': 'RENAME', 'MOVE_TO': 'RENAME',
    'INSERT': 'INSERT_AFTER', 'APPEND_AFTER': 'INSERT_AFTER', 'ADD_AFTER': 'INSERT_AFTER',
    'PREPEND_BEFORE': 'INSERT_BEFORE', 'ADD_BEFORE': 'INSERT_BEFORE',
    'REWRITE': 'RECREATE', 'OVERWRITE': 'RECREATE', 'REPLACE_FILE': 'RECREATE',
    'REMOVE': 'DELETE',
    'snippet_start': 'snippet', 'start_snippet': 'snippet',
    'snippet_end': 'snippet_tail', 'end_snippet': 'snippet_tail', 'tail': 'snippet_tail',
    'new_content': 'content', 'code': 'content', 'body': 'content',
    'scope': 'anchor',
}

FENCE_RE = re.compile(r'^\s*(?:`{3,}|~{3,})\s*[\w+.#-]*\s*$')
HEADER_RE = re.compile(r'^(\S+)\s+AP\s+v?(\d+(?:\.\d+)?)\s*$', re.IGNORECASE)


def strip_markdown_fences(lines: List[str]) -> List[str]:
    """
    Removes the markdown code fences that wrapped the patch in a chat answer.

    Without this, the closing ``` is silently appended to the last `content`
    block and ends up inside the patched source file.
    """
    first = next((i for i, l in enumerate(lines) if l.strip()), None)
    if first is None or not FENCE_RE.match(lines[first]):
        return lines
    out = list(lines)
    out[first] = ''
    for j in range(len(out) - 1, first, -1):
        if not out[j].strip():
            continue
        if FENCE_RE.match(out[j]):
            out[j] = ''
        break
    return out


def resolve_directive_key(raw_key: str, strict: bool, warn) -> Optional[str]:
    """Maps a directive keyword to its canonical form, forgiving case/colon/synonym drift."""
    if raw_key in CANONICAL_KEYS:
        return raw_key
    if strict:
        return None

    key = raw_key.rstrip(':').strip()
    if key in CANONICAL_KEYS:
        warn(f"Directive '{raw_key}' normalized to '{key}'.")
        return key
    if key in KEY_ALIASES:
        warn(f"Non-standard directive '{raw_key}' interpreted as '{KEY_ALIASES[key]}'.")
        return KEY_ALIASES[key]

    low = key.lower()
    for cand in CANONICAL_KEYS:
        if cand.lower() == low:
            warn(f"Directive '{raw_key}' has wrong case, interpreted as '{cand}'.")
            return cand
    for alias, cand in KEY_ALIASES.items():
        if alias.lower() == low:
            warn(f"Non-standard directive '{raw_key}' interpreted as '{cand}'.")
            return cand
    return None


def is_id_like(candidate: str, reference: str) -> bool:
    """
    Decides whether a token may be a drifted patch ID.

    Deliberately conservative: the drift check runs on every line, including
    lines inside a `content` block, so a loose rule would let payload text
    hijack the directive prefix.
    """
    if re.fullmatch(r'[0-9a-fA-F]{8}', candidate):
        return True
    return len(candidate) == len(reference) and re.fullmatch(r'[0-9A-Za-z_]+', candidate) is not None


def parse_ap3_format(patch_file: str, strict: bool = False, silent: bool = False) -> PatchData:
    """Parses the AP delimiter-based format into the standard internal dict structure."""

    def warn(message: str):
        if not silent:
            print(f"  [TOLERANT] {message}")

    with open(patch_file, 'r', encoding='utf-8') as f:
        raw = f.read()
    if raw.startswith('\ufeff'):
        raw = raw[1:]
    lines = strip_markdown_fences(raw.splitlines())

    patch_id = None
    known_ids: List[str] = []
    data: PatchData = {'version': AP_FORMAT_VERSION, 'patch_id': None, 'changes': []}
    current_file_change = None
    current_modification = None
    reading_key = None
    value_lines: List[str] = []
    pending_args = None  # To store args for delayed processing (e.g. CREATE)
    directive_pattern = None
    start_idx = 0

    def rebuild_directive_pattern():
        alternatives = "|".join(re.escape(i) for i in known_ids)
        return re.compile(rf'^(?:{alternatives})\s+(.*)$')

    def adopt_id(new_id: str):
        nonlocal directive_pattern
        if new_id not in known_ids:
            known_ids.append(new_id)
        directive_pattern = rebuild_directive_pattern()

    # --- Header discovery -------------------------------------------------
    for i, line in enumerate(lines):
        stripped_line = line.strip()
        if not stripped_line:
            continue

        match = HEADER_RE.match(stripped_line)
        if match:
            patch_id, version = match.group(1), match.group(2)
            if not re.match(r'^[0-9a-fA-F]{8}$', patch_id):
                if strict:
                    raise ValueError(f"Invalid patch ID '{patch_id}' on line {i+1}. ID MUST be exactly 8 hexadecimal characters.")
                warn(f"Tolerating invalid non-hex or semantic patch ID: '{patch_id}'.")
            if version not in AP_SUPPORTED_VERSIONS:
                if strict:
                    raise ValueError(f"Unsupported AP version '{version}' on line {i+1}. This patcher implements {AP_FORMAT_VERSION}.")
                warn(f"Patch declares AP {version}; parsing it as AP {AP_FORMAT_VERSION}.")
            data['version'] = version
            adopt_id(patch_id)
            start_idx = i + 1
            break

        # Tolerant mode: the model may have dropped the header entirely.
        if not strict:
            potential_match = re.match(
                r'^([0-9a-fA-F]{8})\s+(FILE|REPLACE|INSERT_AFTER|INSERT_BEFORE|DELETE|CREATE|RECREATE|RENAME)\b',
                stripped_line)
            if potential_match:
                patch_id = potential_match.group(1)
                adopt_id(patch_id)
                warn(f"Missing AP header. Auto-detected patch ID: '{patch_id}' from line {i+1}")
                start_idx = i
                break

    if not patch_id:
        raise ValueError(f"Valid AP {AP_FORMAT_VERSION} header not found in the file.")
    data['patch_id'] = patch_id

    paramless = r'(RECREATE|REPLACE|INSERT_AFTER|INSERT_BEFORE|DELETE|CREATE|snippet|anchor|content|snippet_tail|RENAME|END)'
    file_dir = r'(FILE(?:\s+\S.*)?)'
    include_dir = r'((?:include_leading_blank_lines|include_trailing_blank_lines)\s+\d+)'
    drift_pattern = re.compile(rf'^(\S+)\s+({paramless}|{file_dir}|{include_dir})$')

    def flush_value():
        """Commits the collected value block to the directive that opened it."""
        nonlocal current_file_change, current_modification, reading_key, value_lines, pending_args
        if not reading_key:
            return
        start = 0
        while start < len(value_lines) and not value_lines[start].strip():
            start += 1
        end = len(value_lines)
        while end > start and not value_lines[end - 1].strip():
            end -= 1
        value = "\n".join(value_lines[start:end])

        if reading_key == 'CREATE_CONTENT':
            # Speculative: `CREATE` after `FILE` may be followed either by the
            # file body or by an explicit `content` directive. Only a non-empty
            # block is the body.
            if value and current_modification is not None:
                current_modification['content'] = value
        elif reading_key == "path" and current_file_change is not None:
            current_file_change['file_path'] = value
        elif reading_key == "CREATE_PATH":
            # Implicit file creation support
            if value:
                current_file_change = {'modifications': []}
                data['changes'].append(current_file_change)
                current_file_change['file_path'] = value
                if pending_args in NEWLINE_VALS:
                    current_file_change['newline'] = pending_args
            if not current_file_change:
                raise ValueError("Action 'CREATE' used before any FILE directive.")
            current_modification = {'action': 'CREATE'}
            current_file_change['modifications'].append(current_modification)
        elif reading_key == 'RENAME' and current_file_change is not None and not current_modification:
            current_file_change['rename_to'] = value
        elif current_modification is not None:
            current_modification[reading_key] = value
        elif reading_key == 'RENAME' and current_file_change is not None:
            current_file_change['rename_to'] = value

        reading_key, value_lines, pending_args = None, [], None

    # --- Main parsing loop ------------------------------------------------
    for i in range(start_idx, len(lines)):
        line = lines[i]
        line_num = i + 1
        stripped_line = line.strip()

        # Adopt (rather than replace) drifted IDs: a model that alternates
        # between two IDs still produces a fully parseable patch.
        id_drift_match = drift_pattern.match(stripped_line)
        if id_drift_match:
            new_id = id_drift_match.group(1)
            keyword_part = id_drift_match.group(2).split()[0]
            if new_id not in known_ids and keyword_part in CANONICAL_KEYS and is_id_like(new_id, patch_id):
                if strict:
                    raise ValueError(f"Patch ID mismatch on line {line_num}: expected '{patch_id}', found '{new_id}'. Run without --strict to allow ID correction.")
                warn(f"ID drift detected on line {line_num}: '{patch_id}' -> '{new_id}'. Accepting both.")
                adopt_id(new_id)

        match = directive_pattern.match(line)
        if match:
            flush_value()

            parts = match.group(1).strip().split(maxsplit=1)
            if not parts:
                continue
            raw_key, args = parts[0], parts[1] if len(parts) > 1 else None
            key = resolve_directive_key(raw_key, strict, warn)
            if key is None:
                raise ValueError(f"Unknown directive '{raw_key}' on line {line_num}.")

            if key == 'END':
                if args:
                    raise ValueError(f"Directive '{key}' on line {line_num} takes no arguments.")
                break

            elif key == 'FILE':
                current_file_change = {'modifications': []}
                data['changes'].append(current_file_change)
                inline_path = None
                if args:
                    tokens = args.split(maxsplit=1)
                    if tokens[0] in NEWLINE_VALS:
                        current_file_change['newline'] = tokens[0]
                        if len(tokens) > 1:
                            inline_path = tokens[1].strip()
                    else:
                        inline_path = args.strip()
                current_modification = None
                if inline_path:
                    current_file_change['file_path'] = inline_path
                    reading_key = None
                else:
                    reading_key = 'path'

            elif key in ACTION_KEYS:
                if not current_file_change:
                    raise ValueError(f"Action '{key}' on line {line_num} before FILE.")
                if args:
                    raise ValueError(f"Action '{key}' on line {line_num} takes no arguments.")
                current_modification = {'action': key, '_line': line_num}
                current_file_change['modifications'].append(current_modification)

            elif key == 'CREATE':
                if current_file_change and 'file_path' in current_file_change:
                    # Contextual Creation: CREATE used after FILE.
                    current_modification = {'action': 'CREATE', '_line': line_num}
                    current_file_change['modifications'].append(current_modification)
                    reading_key = 'CREATE_CONTENT'
                elif args and args not in NEWLINE_VALS:
                    # Path provided as argument: CREATE path/to/file
                    current_file_change = {'modifications': []}
                    data['changes'].append(current_file_change)
                    current_file_change['file_path'] = args
                    current_modification = {'action': 'CREATE', '_line': line_num}
                    current_file_change['modifications'].append(current_modification)
                    reading_key = 'content'
                else:
                    # Hybrid: acts as key-value (for path) AND action.
                    reading_key = 'CREATE_PATH'
                    pending_args = args

            elif key in VALUE_KEYS:
                if args:
                    raise ValueError(f"Directive '{key}' on line {line_num} takes no arguments.")
                if not current_modification and current_file_change and key == 'content':
                    # Heuristic: a 'content' block directly after 'FILE' implies 'CREATE'.
                    current_modification = {'action': 'CREATE', '_line': line_num}
                    current_file_change['modifications'].append(current_modification)
                if not current_modification:
                    raise ValueError(f"'{key}' on line {line_num} outside modification.")
                if key in ('snippet', 'anchor') and 'content' in current_modification:
                    # A locator after a finished modification means the model
                    # forgot to repeat the Action Directive. Silently overwriting
                    # the previous locator would drop a change without a trace.
                    previous_action = current_modification.get('action')
                    if strict:
                        raise ValueError(
                            f"Directive '{key}' on line {line_num} starts a new modification "
                            f"but no Action Directive precedes it.")
                    warn(f"Missing Action Directive before '{key}' on line {line_num}. "
                         f"Starting a new '{previous_action}' modification.")
                    current_modification = {'action': previous_action, '_line': line_num}
                    current_file_change['modifications'].append(current_modification)
                elif key in current_modification:
                    if strict or key == 'content':
                        raise ValueError(
                            f"Duplicate '{key}' directive on line {line_num} within one modification.")
                    warn(f"Duplicate '{key}' on line {line_num}; the last one wins.")
                reading_key = key

            elif key == 'RENAME':
                if not current_file_change:
                    raise ValueError(f"'{key}' on line {line_num} outside file block.")
                if current_file_change.get('modifications'):
                    raise ValueError(f"'{key}' on line {line_num} cannot be combined with other actions in the same file block.")
                if args:
                    current_file_change['rename_to'] = args.strip()
                    reading_key = None
                else:
                    reading_key = 'RENAME'

            elif key in ARG_KEYS:
                if not current_modification:
                    raise ValueError(f"'{key}' on line {line_num} outside modification.")
                if not args:
                    raise ValueError(f"Directive '{key}' on line {line_num} requires an argument.")
                try:
                    current_modification[key] = int(args)
                except ValueError:
                    raise ValueError(f"Argument for '{key}' on line {line_num} must be an integer.")

            else:
                raise ValueError(f"Unknown directive '{key}' on line {line_num}.")

        elif reading_key:
            if not strict and reading_key in ('path', 'RENAME', 'CREATE_PATH') and stripped_line.startswith('#'):
                pass  # Ignore comments inside path values
            else:
                value_lines.append(line)
        elif not stripped_line:
            pass
        elif not strict and stripped_line.startswith('#'):
            pass  # Allow comments between directives in tolerant mode
        elif not strict and FENCE_RE.match(line):
            pass  # Stray markdown fence between directives
        elif (not strict and current_modification is not None
              and current_modification.get('action') in ('REPLACE', 'DELETE', 'INSERT_AFTER', 'INSERT_BEFORE')
              and 'snippet' not in current_modification and 'content' not in current_modification):
            # The model wrote the locator right after the Action Directive and
            # forgot the `snippet` keyword.
            warn(f"Text on line {line_num} follows an Action Directive with no "
                 f"'snippet' keyword. Treating it as the snippet.")
            reading_key = 'snippet'
            value_lines = [line]
        else:
            raise ValueError(f"Unexpected content on line {line_num}: '{line}'")

    flush_value()

    for change in data['changes']:
        path_value = (change.get('file_path') or '').strip()
        if not path_value:
            raise ValueError(
                "A FILE block has an empty path. The path MUST be given either as "
                "the value block of the FILE directive or as its inline argument.")
        if len(path_value.splitlines()) > 1:
            raise ValueError(f"A FILE block declares a multi-line path: {path_value!r}")

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
    # PERFORMANCE GUARD:
    # Fuzzy matching on large blocks is extremely expensive (O(N * M)).
    # If the snippet is large (e.g. > 1KB or > 20 lines), skipping fuzzy match
    # prevents the patcher from hanging on failure.
    if len(snippet) > 1000 or len(snippet.splitlines()) > 20:
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

def reindent_content(content: str, start_pos: int, end_pos: int, new_content: str,
                     action: str, strict: bool, warn) -> str:
    """
    Restores the indentation a model dropped from a `content` block.

    Locators are matched whitespace-insensitively, which regularly convinces a
    model that indentation is irrelevant for `content` too. It is not: `content`
    is inserted verbatim. When the target region is indented and *every* line of
    `content` sits at column 0, the intent is unambiguous, and silently writing
    flattened code would break any indentation-sensitive language.
    """
    if strict:
        return new_content
    region_lines = [l for l in content[start_pos:end_pos].split('\n') if l.strip()]
    if not region_lines:
        return new_content
    reference = region_lines[-1] if action == 'INSERT_AFTER' else region_lines[0]
    base_indent = leading_whitespace(reference)
    if not base_indent:
        return new_content
    new_lines = new_content.split('\n')
    non_blank = [l for l in new_lines if l.strip()]
    if not non_blank or min(len(leading_whitespace(l)) for l in non_blank) > 0:
        return new_content
    warn(f"'content' starts at column 0 while the target is indented by {len(base_indent)}. "
         f"Re-indenting the inserted block to match.")
    return '\n'.join(base_indent + l if l.strip() else l for l in new_lines)

def find_partial_line_matches(content: str, snippet: Optional[str], limit: int = 3) -> List[Dict[str, Any]]:
    """
    Detects the single most common locator mistake: a snippet that is only a
    *fragment* of a line. Reporting it explicitly turns a mystifying
    'Snippet not found' into an actionable message.
    """
    snippet_lines = [l.strip() for l in (snippet or "").strip().splitlines() if l.strip()]
    if len(snippet_lines) != 1:
        return []
    needle = snippet_lines[0]
    if len(needle) < 4:
        return []
    hits = []
    for idx, line in enumerate(content.splitlines()):
        stripped = line.strip()
        if stripped != needle and needle in stripped:
            hits.append({"line_number": idx + 1, "text": line})
            if len(hits) >= limit:
                break
    return hits

def line_number_at(content: str, offset: int) -> int:
    return content.count('\n', 0, offset) + 1

def find_target_in_content(content: str, anchor: Optional[str], snippet: str, debug: bool = False, last_match_end: int = 0, allow_repeat: bool = False) -> Tuple[Optional[Tuple[int, int]], Dict[str, Any]]:
    if not anchor:
        if snippet and snippet.strip() == '^':
            return (0, 0), {}
        if snippet and snippet.strip() == '$':
            return (len(content), len(content)), {}

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

        # === ROBUST OVERLAP & CONTAINMENT DETECTION ===
        s_lines = [l.strip() for l in (snippet or "").strip().splitlines() if l.strip()]
        a_lines = [l.strip() for l in (anchor or "").strip().splitlines() if l.strip()]
        is_overlap = False
        if s_lines and a_lines:
            # 1. Suffix/Prefix overlap: check if any suffix of a_lines matches a prefix of s_lines
            for k in range(1, min(len(a_lines), len(s_lines)) + 1):
                if a_lines[-k:] == s_lines[:k]:
                    is_overlap = True
                    break

            # 2. Containment: check if s_lines is a sublist of a_lines
            if not is_overlap:
                for i in range(len(a_lines) - len(s_lines) + 1):
                    if a_lines[i:i+len(s_lines)] == s_lines:
                        is_overlap = True
                        break

            # 3. Containment: check if a_lines is a sublist of s_lines
            if not is_overlap:
                for i in range(len(s_lines) - len(a_lines) + 1):
                    if s_lines[i:i+len(a_lines)] == a_lines:
                        is_overlap = True
                        break

        if is_overlap:
             debug_print(debug, "OVERLAP DETECTED", message="Snippet overlaps with or is contained in Anchor. Including Anchor in search scope.")
             search_space, offset, anchor_found = content[anchor_start:], anchor_start, True
        else:
             search_space, offset, anchor_found = content[anchor_end:], anchor_end, True

    debug_print(debug, "SNIPPET SEARCH", snippet=snippet, search_space_len=len(search_space))
    occurrences = smart_find(search_space, snippet)

    # === SNIPPET CURSOR FILTER ===
    # Matches before the cursor belong to already-processed regions, so they are
    # never candidates. This is what makes sequential top-to-bottom patching work.
    if occurrences:
        forward_occurrences = [o for o in occurrences if (o[0] + offset) >= last_match_end]
        if forward_occurrences:
            # An anchor-less snippet that still matches several places is
            # genuinely ambiguous: picking the first one silently patches a
            # random occurrence. `allow_repeat` is set only when the patch
            # itself repeats this locator, which is the documented way to
            # address N identical blocks in order.
            if len(forward_occurrences) > 1 and not anchor and not allow_repeat:
                positions = [line_number_at(content, o[0] + offset) for o in forward_occurrences]
                return None, {
                    "code": "AMBIGUOUS_MATCH",
                    "message": (f"Snippet matches {len(forward_occurrences)} places "
                                f"(lines {', '.join(str(p) for p in positions[:10])}). "
                                f"Add an 'anchor' to disambiguate, or extend the snippet."),
                    "context": {"snippet": snippet, "count": len(forward_occurrences), "match_lines": positions},
                }
            occurrences = [forward_occurrences[0]]
        else:
            # All occurrences were behind the cursor. Treat as not found.
            occurrences = []

    if not occurrences:
        preview_lines = [l for l in search_space.splitlines() if l.strip()]
        context = {
            "snippet": snippet,
            "anchor": anchor,
            "anchor_found": anchor_found,
            "fuzzy_matches": get_fuzzy_matches(search_space, snippet),
            "search_space_preview": "\n".join(preview_lines[:7])
        }
        partial = find_partial_line_matches(search_space, snippet)
        if partial:
            context["partial_line_matches"] = partial
            context["hint"] = ("The snippet appears as a fragment of an existing line. "
                               "`ap` locators MUST cover whole lines: extend the snippet "
                               "to the full line, from its first non-blank character to its last.")
        return None, {"code": "SNIPPET_NOT_FOUND", "message": "Snippet not found.", "context": context}

    start_pos, end_pos = occurrences[0]
    return (start_pos + offset, end_pos + offset), {}

# --- LLM-oriented failure report ------------------------------------------
# When a patch does not apply cleanly the next step is almost always "hand the
# failure back to the model that produced it". `afailed.ap` is the machine
# replay of the failed modifications; `afailed.md` is the briefing that lets a
# model fix them in one round trip instead of guessing.

FIX_HINTS = {
    "AMBIGUOUS_MATCH":
        "The `snippet` matches several places, so the patcher refuses to guess. Either extend the "
        "`snippet` downwards until it covers a unique block, or add an `anchor` holding the nearest "
        "unique construct above the target (a function signature, a class line, a unique comment). "
        "If you really meant to change every occurrence, emit one modification per occurrence, all "
        "with the same locator, in top-to-bottom order.",
    "SNIPPET_NOT_FOUND":
        "The `snippet` does not exist in the search scope. Copy the locator verbatim from the "
        "'Current content' section below - do not retype it from memory. Remember that a locator "
        "MUST cover whole lines and that the search starts after the previous modification of the "
        "same file (top-to-bottom order is mandatory).",
    "ANCHOR_NOT_FOUND":
        "The `anchor` does not exist in the file. Copy it verbatim from the 'Current content' "
        "section, or drop the `anchor` entirely if the `snippet` is already unique.",
    "AMBIGUOUS_ANCHOR":
        "The `anchor` occurs several times and the `snippet` could not be tied to exactly one of "
        "them. Choose a larger or more distinctive anchor.",
    "snippet_tail_NOT_FOUND":
        "`snippet_tail` was not found after `snippet`. The two MUST be independent: `snippet_tail` "
        "marks the *end* of the block and must appear strictly after `snippet` in the file. Do not "
        "put the whole block into `snippet`, and do not repeat `content` in `snippet_tail`.",
    "EMPTY_REPLACE":
        "`REPLACE` with empty `content` is refused because it is indistinguishable from a truncated "
        "answer. Use `DELETE` to remove code.",
    "MISSING_CONTENT":
        "The action requires a `content` block and none was given. Check that the answer was not cut "
        "off and that the `content` directive carries the patch ID prefix.",
    "INVALID_MODIFICATION":
        "The modification is structurally incomplete. Every REPLACE/DELETE/INSERT_* needs a `snippet`; "
        "every REPLACE/INSERT_*/RECREATE needs a `content`.",
    "FILE_NOT_FOUND":
        "The target file does not exist. Check the path (it is relative to the project root) or use "
        "`CREATE` if the file is meant to be new.",
    "FILE_EXISTS":
        "`CREATE` refuses to overwrite a non-empty file. Use `RECREATE` to replace its whole content, "
        "or ordinary REPLACE/INSERT modifications to edit it in place.",
    "PATH_IS_FILE":
        "A file already exists where a directory was requested.",
    "DESTINATION_EXISTS":
        "The `RENAME` destination already exists. Delete it first or pick another name.",
    "INVALID_FILE_PATH":
        "The path escapes the project root or is malformed. Paths are relative to the project root "
        "and MUST NOT contain `..`.",
    "INVALID_PATCH_FILE":
        "The patch itself could not be parsed. Re-read the directive syntax: every directive line is "
        "`<patch-id> KEYWORD`, the ID is the same 8 hex characters everywhere, and no `#` comments "
        "may appear inside the patch body.",
    "AFAILED_EXISTS":
        "A previous failure report is still present. Remove it before applying a new patch.",
}


def _fence(text: str, lang: str = "") -> str:
    body = text if text.endswith('\n') else text + '\n'
    fence = "```"
    while fence in body:
        fence += "`"
    return f"{fence}{lang}\n{body}{fence}\n"


def _numbered(text: str, limit: int = 400) -> str:
    lines = text.split('\n')
    truncated = len(lines) > limit
    shown = lines[:limit]
    width = len(str(len(shown)))
    body = '\n'.join(f"{str(i + 1).rjust(width)} | {l}" for i, l in enumerate(shown))
    if truncated:
        body += f"\n... ({len(lines) - limit} more lines omitted)"
    return body


def write_llm_report(path: str, patch_content: str, file_reports: List[Dict[str, Any]],
                     fatal: Optional[Dict[str, Any]] = None, strict: bool = False) -> None:
    """Writes `afailed.md`: everything a model needs to repair the patch in one step."""
    out: List[str] = []
    total = sum(len(fr['failed']) for fr in file_reports) + (1 if fatal else 0)
    out.append(f"# ap patch report: {total} problem(s)\n")
    out.append(
        "This file was written by the `ap` patcher for the model that generated the patch.\n"
        "**Read it, then emit a NEW `ap` patch containing only the fixes below.**\n"
        "Do not resend modifications that already applied - the files on disk already contain them,\n"
        "and the 'Current content' sections below show their state *after* the partial application.\n")

    if fatal:
        err = fatal.get('error', {})
        out.append("## Fatal error\n")
        out.append(f"- **Code:** `{err.get('code')}`")
        if fatal.get('file_path'):
            out.append(f"- **File:** `{fatal['file_path']}`")
        out.append(f"- **Message:** {err.get('message')}\n")
        hint = FIX_HINTS.get(err.get('code'))
        if hint:
            out.append(f"**How to fix:** {hint}\n")
        if strict:
            out.append("The patcher ran in strict mode, so **nothing was written to disk**: "
                       "the whole patch must be resent, corrected.\n")

    for fr in file_reports:
        ok = fr['total_mods'] - len(fr['failed'])
        out.append(f"## File `{fr['file_path']}`\n")
        out.append(f"{ok} of {fr['total_mods']} modification(s) applied or skipped as already present; "
                   f"{len(fr['failed'])} failed.\n")

        for item in fr['failed']:
            mod = item['mod']
            err = item['error']
            line = mod.get('_line')
            where = f" (patch line {line})" if line else ""
            out.append(f"### Modification #{item['mod_idx'] + 1} - `{mod.get('action') or 'UNKNOWN'}`{where}\n")
            out.append(f"- **Code:** `{err.get('code')}`")
            out.append(f"- **Message:** {err.get('message')}\n")
            hint = FIX_HINTS.get(err.get('code'))
            if hint:
                out.append(f"**How to fix:** {hint}\n")

            ctx = err.get('context') or {}
            if ctx.get('match_lines'):
                out.append("Matched at lines: " + ", ".join(str(x) for x in ctx['match_lines']) + "\n")
            if ctx.get('hint'):
                out.append(f"{ctx['hint']}\n")
            if ctx.get('partial_line_matches'):
                out.append("Lines that *contain* the snippet as a fragment:\n")
                out.append(_fence('\n'.join(
                    f"{m['line_number']} | {m['text']}" for m in ctx['partial_line_matches'])))
            if ctx.get('fuzzy_matches'):
                out.append("Closest existing text (did you mean one of these?):\n")
                for m in ctx['fuzzy_matches']:
                    out.append(f"- line {m['line_number']}, similarity {m['score']}:")
                    out.append(_fence(m['text']))

            out.append("What the failed modification asked for:\n")
            sent = []
            for key in ('anchor', 'snippet', 'snippet_tail', 'content'):
                if key in mod:
                    sent.append(f"[{key}]\n{mod[key]}")
            out.append(_fence('\n\n'.join(sent) if sent else '(no locators)'))

        if fr['original'] != fr['current']:
            diff = difflib.unified_diff(
                fr['original'].splitlines(keepends=True), fr['current'].splitlines(keepends=True),
                fromfile=f"a/{fr['file_path']}", tofile=f"b/{fr['file_path']}")
            out.append("### What the patcher already changed in this file\n")
            out.append(_fence(''.join(diff), 'diff'))
        else:
            out.append("### This file was not modified at all\n")

        out.append("### Current content of the file, as it is on disk right now\n")
        out.append("Use these exact lines when building new locators.\n")
        out.append(_fence(_numbered(fr['current'])))

    if patch_content:
        out.append("## The patch that failed\n")
        out.append(_fence(patch_content))

    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(out))
    except IOError:
        pass
def apply_patch(patch_file: str, project_dir: str, dry_run: bool = False, json_report: bool = False, debug: bool = False, strict: bool = False, failure_report_path: str = None, create_failure_case: bool = False, silent: bool = False) -> Dict[str, Any]:
    patch_content = ""
    try:
        with open(patch_file, 'r', encoding='utf-8') as f:
            patch_content = f.read()
    except (IOError, FileNotFoundError):
        # Let parse_ap3_format handle the error reporting.
        # patch_content will be empty, which is acceptable for the failure case report.
        pass

    def report_idempotency_skip(reason: str):
        debug_print(debug, "IDEMPOTENCY SKIP", reason=reason)
        if not silent:
            print(f"  ~ SKIPPED (Idempotency): Looks like it's already applied. Reason: {reason}")
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
        try:
            write_llm_report(os.path.join(project_dir, "afailed.md"), patch_content,
                             llm_file_reports, fatal=details, strict=strict)
        except Exception:
            pass
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

            for key in ['anchor', 'snippet', 'snippet_tail']:
                if ctx.get(key): print_block(key.replace('_', ' ').title(), ctx[key])

            if ctx.get('anchor_found') and ctx.get('search_space_preview'):
                print("  Context following found anchor (Actual File Content):")
                for line in ctx['search_space_preview'].splitlines():
                    print(f"    {line}")

            if ctx.get('fuzzy_matches'):
                print("  Did you mean one of these?")
                for match in ctx['fuzzy_matches']:
                    print(f"    Line {match['line_number']} (Score: {match['score']}):")
                    actual_text = (match.get('text') or "").splitlines(keepends=True)
                    expected_text = (ctx.get('snippet') or "").strip().splitlines(keepends=True)
                    diff = difflib.unified_diff(
                        expected_text, actual_text,
                        fromfile="expected snippet", tofile="actual text (in file)"
                    )
                    print("      " + "".join(diff).replace("\n", "\n      "))

        return details

    afailed_path = os.path.join(project_dir, "afailed.ap")
    if not strict and os.path.exists(afailed_path):
        err_msg = f"afailed.ap exists at {afailed_path}. Please remove or rename it before running."
        return report_error({"status": "FAILED", "error": {"code": "AFAILED_EXISTS", "message": err_msg}})

    try: data = parse_ap3_format(patch_file, strict=strict, silent=silent)
    except (ValueError, FileNotFoundError) as e:
        err_details = {"status": "FAILED", "error": { "code": "INVALID_PATCH_FILE", "message": str(e) }}
        if create_failure_case:
            create_failure_case_file("afailed.log", err_details, None)
        return report_error(err_details)

    patch_id_str = data.get('patch_id') or "00000000"

    failed_changes_output = []
    write_plan = []
    llm_file_reports: List[Dict[str, Any]] = []
    afailed_md_path = os.path.join(project_dir, "afailed.md")

    for change in data.get('changes', []):
        if 'file_path' not in change:
            err_details = {"status": "FAILED", "error": {"code": "INVALID_PATCH_FILE", "message": "Missing 'file_path' for a change block."}}
            if create_failure_case:
                create_failure_case_file("afailed.log", err_details, None)
            return report_error(err_details)
        original_relative_path = change['file_path']
        is_explicit_dir = original_relative_path.endswith('/') or original_relative_path.endswith('\\')
        relative_path = original_relative_path.rstrip('/\\') or original_relative_path
        stripped_prefix = None

        # Path search heuristic (auto-detect if we are inside a subtree)
        if not os.path.exists(os.path.join(project_dir, relative_path)):
            parts = relative_path.replace('\\', '/').split('/')
            found = False
            for i in range(1, len(parts)):
                test_path = '/'.join(parts[i:])
                if os.path.exists(os.path.join(project_dir, test_path)):
                    relative_path = test_path
                    stripped_prefix = '/'.join(parts[:i])
                    found = True
                    break

            if not found:
                project_dir_abs = os.path.abspath(project_dir).replace('\\', '/')
                for i in range(len(parts) - 1, 0, -1):
                    prefix = '/'.join(parts[:i])
                    if project_dir_abs.endswith('/' + prefix) or project_dir_abs == prefix:
                        relative_path = '/'.join(parts[i:])
                        stripped_prefix = prefix
                        break

        # SECURITY: Perform path validation before any filesystem operations.
        real_project_dir = os.path.realpath(project_dir)
        try:
            real_file_path = os.path.realpath(os.path.join(project_dir, relative_path))
            if not real_file_path.startswith(os.path.join(real_project_dir, '')):
                raise ValueError("Path traversal detected.")
        except Exception: # Catches errors from invalid paths like on Windows
            err_details = {"status": "FAILED", "file_path": relative_path, "error": {"code": "INVALID_FILE_PATH", "message": "Path traversal detected or invalid path format."}}
            if not strict:
                if not silent: print("  - FAILED: Path traversal detected or invalid path format.")
                if create_failure_case: create_failure_case_file(os.path.join(project_dir, "afailed.log"), err_details, None)
                failed_changes_output.append(change)
                continue
            else:
                if create_failure_case:
                    create_failure_case_file(os.path.join(project_dir, "afailed.log"), err_details, None)
                return report_error(err_details)

        file_path = os.path.join(project_dir, relative_path)
        newline_mode = change.get('newline')
        newline_char = {'LF': '\n', 'CRLF': '\r\n', 'CR': '\r'}.get(newline_mode) or (detect_line_endings(file_path) if os.path.exists(file_path) else os.linesep)
        debug_print(debug, "PLANNING FOR FILE", file=file_path, newline_mode=newline_mode or "DETECTED", detected_newline=newline_char)

        if not silent:
            print(f"\nFile: {relative_path}")

        terminal_op_planned = False
        # CONTEXTUAL FILE DELETION:
        # If a file block contains exactly one modification, which is a `DELETE`
        # action with no other locators, we treat it as a command to delete the file.
        mods = change.get('modifications', [])
        if len(mods) == 1 and mods[0].get('action') == 'DELETE' and not (set(mods[0]) - {'action', '_line'}):
            if not os.path.exists(file_path):
                report_idempotency_skip(f"Path to delete does not exist: {file_path}")
                continue
            write_plan.append(('DELETE_PATH', file_path, None, relative_path))
            if not silent:
                print("  + SUCCESS: File deleted.")
            continue

        if 'rename_to' in change:
            new_relative_path = change['rename_to']
            if stripped_prefix:
                new_parts = new_relative_path.replace('\\', '/').split('/')
                prefix_parts = stripped_prefix.split('/')
                if new_parts[:len(prefix_parts)] == prefix_parts:
                    new_relative_path = '/'.join(new_parts[len(prefix_parts):])

            new_file_path = os.path.join(project_dir, new_relative_path)

            try:
                real_new_file_path = os.path.realpath(new_file_path)
                if not real_new_file_path.startswith(os.path.join(real_project_dir, '')):
                    raise ValueError("Path traversal detected.")
            except Exception:
                err_details = {"status": "FAILED", "file_path": relative_path, "error": {"code": "INVALID_FILE_PATH", "message": "Path traversal detected in new rename path."}}
                if not strict:
                    if not silent: print("  - FAILED: Path traversal detected in new rename path.")
                    if create_failure_case: create_failure_case_file(os.path.join(project_dir, "afailed.log"), err_details, None)
                    failed_changes_output.append(change)
                    continue
                else:
                    if create_failure_case: create_failure_case_file(os.path.join(project_dir, "afailed.log"), err_details, None)
                    return report_error(err_details)

            if os.path.exists(new_file_path):
                # Idempotency check: if source is gone but dest exists, we're good.
                if not os.path.exists(file_path):
                    report_idempotency_skip(f"Source does not exist, but destination does. Assuming rename complete: {new_file_path}")
                    continue
                err_details = {"status": "FAILED", "file_path": relative_path, "error": {"code": "DESTINATION_EXISTS", "message": "Rename destination already exists."}}
                if not strict:
                    if not silent: print("  - FAILED: Rename destination already exists.")
                    if create_failure_case: create_failure_case_file("afailed.log", err_details, None)
                    failed_changes_output.append(change)
                    continue
                else:
                    if create_failure_case: create_failure_case_file("afailed.log", err_details, None)
                    return report_error(err_details)

            if not os.path.exists(file_path):
                err_details = {"status": "FAILED", "file_path": relative_path, "error": { "code": "FILE_NOT_FOUND", "message": "Target for rename not found." }}
                if not strict:
                    if not silent: print("  - FAILED: Target for rename not found.")
                    if create_failure_case: create_failure_case_file("afailed.log", err_details, "")
                    failed_changes_output.append(change)
                    continue
                else:
                    if create_failure_case: create_failure_case_file("afailed.log", err_details, "")
                    return report_error(err_details)

            write_plan.append(('RENAME', file_path, new_file_path, relative_path))
            if not silent:
                print(f"  + SUCCESS: Renamed to {new_relative_path}")
            continue

        original_content = ""
        file_existed = os.path.exists(file_path)
        if file_existed and os.path.isdir(file_path):
            pass # It's a directory, don't try to read it. The logic below will handle it.
        elif file_existed:
            with open(file_path, 'r', encoding='utf-8', newline=None) as f: original_content = f.read()
        else: # File does not exist
            if any(mod.get('action') in ('CREATE', 'RECREATE') for mod in change.get('modifications', [])):
                original_content = ""
            else:
                err_details = {"status": "FAILED", "file_path": relative_path, "error": { "code": "FILE_NOT_FOUND", "message": "Target file not found." }}
                if not strict:
                    if not silent: print("  - FAILED: Target file not found.")
                    if create_failure_case: create_failure_case_file("afailed.log", err_details, "")
                    failed_changes_output.append(change)
                    continue
                else:
                    if create_failure_case:
                        create_failure_case_file("afailed.log", err_details, "")
                    return report_error(err_details)

        internal_newline = '\n'
        working_content = original_content.replace('\r\n', internal_newline).replace('\r', internal_newline)
        # A locator repeated across several modifications of the same file is
        # the documented way to address N identical blocks in order. Any other
        # multi-match is real ambiguity and must not be resolved by guessing.
        def locator_key(m: Modification):
            return (normalize_block(m.get('anchor')), normalize_block(m.get('snippet')),
                    normalize_block(m.get('snippet_tail')))
        repeated_locators = set()
        seen_locators = set()
        for m in change.get('modifications', []):
            if not (m.get('snippet') or m.get('anchor')):
                continue
            k = locator_key(m)
            if k in seen_locators:
                repeated_locators.add(k)
            seen_locators.add(k)

        pending_mods = list(enumerate(change.get('modifications', [])))
        final_failed_mods = []
        pass_number = 1

        while pending_mods:
            made_progress = False
            failed_in_this_pass = []
            last_mod_end_pos = 0

            for mod_idx, mod in pending_mods:
                action = mod.get('action')
                debug_print(debug, f"MODIFICATION #{mod_idx+1} (Pass {pass_number})", action=action)

                content_to_add = clean_lines(mod.get('content'))

                if action in ['REPLACE', 'INSERT_AFTER', 'INSERT_BEFORE', 'RECREATE']:
                    if 'content' not in mod:
                        error = {"code": "MISSING_CONTENT", "message": f"Action '{action}' requires 'content' directive.", "context": {}}
                        report = {"status": "FAILED", "file_path": relative_path, "mod_idx": mod_idx, "error": error}
                        if not strict:
                            failed_in_this_pass.append((mod_idx, mod, report, error, original_content))
                            continue
                        else:
                            if create_failure_case:
                                create_failure_case_file("afailed.log", report, original_content)
                            return report_error(report)
                    elif action == 'REPLACE' and not content_to_add:
                        error = {"code": "EMPTY_REPLACE", "message": "REPLACE with empty content is not allowed. Use DELETE instead.", "context": {}}
                        report = {"status": "FAILED", "file_path": relative_path, "mod_idx": mod_idx, "error": error}
                        if not strict:
                            failed_in_this_pass.append((mod_idx, mod, report, error, original_content))
                            continue
                        else:
                            if create_failure_case:
                                create_failure_case_file("afailed.log", report, original_content)
                            return report_error(report)

                if action == 'RECREATE':
                    if working_content == (content_to_add or ""):
                        report_idempotency_skip("RECREATE content already matches.")
                        continue
                    working_content = content_to_add or ""
                    last_mod_end_pos = len(working_content)
                    made_progress = True
                    if not silent:
                        pass_str = f" (Pass {pass_number})" if pass_number > 1 else ""
                        print(f"  + SUCCESS: Mod #{mod_idx + 1} (RECREATE) applied{pass_str}.")
                    continue
                if not action:
                    error = {"code": "INVALID_MODIFICATION", "message": "'action' is required.", "context": {}}
                    report = {"status": "FAILED", "file_path": relative_path, "mod_idx": mod_idx, "error": error}
                    if not strict:
                        failed_in_this_pass.append((mod_idx, mod, report, error, original_content))
                        continue
                    else:
                        if create_failure_case:
                            create_failure_case_file("afailed.log", report, original_content)
                        return report_error(report)

                # Clean inputs from the patch to avoid issues with trailing whitespace in the patch file itself.
                snippet_val = clean_lines(mod.get('snippet'))
                snippet_tail = clean_lines(mod.get('snippet_tail'))
                anchor_val = clean_lines(mod.get('anchor'))

                if not strict and not snippet_val and anchor_val and action in ['REPLACE', 'DELETE', 'INSERT_AFTER', 'INSERT_BEFORE']:
                    snippet_val = anchor_val
                    anchor_val = None
                    if not silent:
                        print(f"  [TOLERANT] Mod #{mod_idx + 1}: Missing 'snippet'. Using 'anchor' as snippet.")

                # === SAFE CREATE (File or Directory) ===
                if action == 'CREATE':
                    error_to_report = None
                    # Case 1: Create a directory
                    if content_to_add is None or (content_to_add == "" and is_explicit_dir):
                        # Idempotency check: if it's already a dir, we're done.
                        if os.path.isdir(file_path):
                            report_idempotency_skip("Directory already exists.")
                            pending_mods = []
                            break
                        # If it's a file, it's an error.
                        if os.path.exists(file_path):
                            error_to_report = {"code": "PATH_IS_FILE", "message": "Cannot create directory, a file exists at the path."}

                        if not error_to_report:
                            # This is a directory creation, so it's a terminal action for this file block.
                            write_plan.append(('CREATE_DIR', file_path, None, relative_path))
                            terminal_op_planned = True
                            working_content = "" # No further processing
                            made_progress = True
                            if not silent:
                                pass_str = f" (Pass {pass_number})" if pass_number > 1 else ""
                                print(f"  + SUCCESS: Mod #{mod_idx + 1} (CREATE) applied{pass_str}.")
                            pending_mods = []
                            break

                    # Case 2: Create a file (content is not None)
                    else:
                        if os.path.isfile(file_path):
                            with open(file_path, 'r', encoding='utf-8', newline=None) as f_check:
                                existing_content = f_check.read().replace('\r\n', internal_newline).replace('\r', internal_newline)

                            normalized_existing = "\n".join(l.strip() for l in existing_content.strip().splitlines())
                            normalized_new = "\n".join(l.strip() for l in (content_to_add or "").strip().splitlines())

                            if normalized_existing == normalized_new:
                                report_idempotency_skip("File exists with matching content.")
                                pending_mods = []
                                break
                            elif not existing_content.strip():
                                debug_print(debug, "OVERWRITE EMPTY", message="File exists but is empty. Overwriting.")
                            else:
                                error_to_report = {"code": "FILE_EXISTS", "message": "Target file exists and is not empty."}

                        if not error_to_report:
                            working_content = (content_to_add or "").replace('\r\n', internal_newline).replace('\r', internal_newline)
                            made_progress = True
                            if not silent:
                                pass_str = f" (Pass {pass_number})" if pass_number > 1 else ""
                                print(f"  + SUCCESS: Mod #{mod_idx + 1} (CREATE) applied{pass_str}.")
                            continue

                    if error_to_report:
                        report = {"status": "FAILED", "file_path": relative_path, "mod_idx": mod_idx, "error": error_to_report}
                        if not strict:
                            failed_in_this_pass.append((mod_idx, mod, report, error_to_report, original_content))
                            continue
                        else:
                            if create_failure_case:
                                create_failure_case_file("afailed.log", report, original_content)
                            return report_error(report)

                # Heuristic: If snippet_tail is identical to content, the AI likely confused "what to replace" with "what to replace it with".
                # Treat this as a point-based replacement.
                if snippet_val and snippet_tail and content_to_add:
                    norm_end = "\n".join(l.strip() for l in snippet_tail.strip().splitlines())
                    norm_content = "\n".join(l.strip() for l in content_to_add.strip().splitlines())
                    if norm_end == norm_content:
                        debug_print(debug, "HEURISTIC APPLIED", message="snippet_tail matches content. Treating as single snippet.")
                        snippet_tail = None

                # Heuristic: If snippet and snippet_tail are identical, treat as a single-snippet operation.
                if snippet_val and snippet_tail and snippet_val.strip() == snippet_tail.strip():
                    debug_print(debug, "HEURISTIC APPLIED", message="snippet is identical to snippet_tail. Treating as single snippet.")
                    snippet_tail = None
                # Heuristic: Auto-correct AI error where snippet_tail is part of snippet (now snippet_val).
                if snippet_val and snippet_tail and snippet_val.strip().endswith(snippet_tail.strip()):
                    debug_print(debug, "HEURISTIC APPLIED", message="snippet_tail is suffix of snippet. Treating as single snippet.")
                    snippet_tail = None

                target_pos, error = None, {}

                # Logic: If snippet_tail exists, it is a range operation starting at snippet_val.
                # If only snippet_val exists, it is a point operation.

                allow_repeat = locator_key(mod) in repeated_locators

                if snippet_tail is not None:
                    if snippet_val is None:
                        error = {"code": "INVALID_MODIFICATION", "message": "Range requires 'snippet'.", "context": {}}
                    elif action not in ['REPLACE', 'DELETE', 'INSERT_AFTER', 'INSERT_BEFORE']:
                        error = {"code": "INVALID_MODIFICATION", "message": f"Action '{action}' does not support range.", "context": {}}
                    elif action in ['INSERT_AFTER', 'INSERT_BEFORE'] and strict:
                        error = {"code": "INVALID_MODIFICATION", "message": f"Action '{action}' is a point operation and MUST NOT carry 'snippet_tail'.", "context": {}}
                    else:
                        if action in ['INSERT_AFTER', 'INSERT_BEFORE'] and not silent:
                            print(f"  [TOLERANT] Mod #{mod_idx + 1}: '{action}' is a point action; "
                                  f"inserting at the {'end' if action == 'INSERT_AFTER' else 'start'} of the given range.")
                        if snippet_val and snippet_val.strip() == '^':
                            start_range_begin, start_range_end = 0, 0
                            error = None
                        else:
                            start_pos_info, error = find_target_in_content(working_content, anchor_val, snippet_val, debug, last_mod_end_pos, allow_repeat)
                            if not error: start_range_begin, start_range_end = start_pos_info

                        if not error:
                            if snippet_tail and snippet_tail.strip() == '$':
                                target_pos = (start_range_begin, len(working_content))
                            else:
                                end_occurrences = smart_find(working_content[start_range_end:], snippet_tail)
                                if end_occurrences:
                                    end_range_begin_rel, end_range_end_rel = end_occurrences[0]
                                    target_pos = (start_range_begin, start_range_end + end_range_end_rel)
                                else:
                                    # Reversed range: the model swapped start and end.
                                    before = smart_find(working_content[:start_range_begin], snippet_tail) if not strict else []
                                    if before:
                                        if not silent:
                                            print(f"  [TOLERANT] Mod #{mod_idx + 1}: 'snippet_tail' occurs BEFORE 'snippet'. "
                                                  f"Treating the pair as a reversed range.")
                                        target_pos = (before[-1][0], start_range_end)
                                    else:
                                        error = {"code": "snippet_tail_NOT_FOUND", "message": "End snippet not found.", "context": {"snippet": snippet_val, "snippet_tail": snippet_tail}}

                elif snippet_val is not None:
                     target_pos, error = find_target_in_content(working_content, anchor_val, snippet_val, debug, last_mod_end_pos, allow_repeat)

                elif action != 'CREATE':
                    error = {"code": "INVALID_MODIFICATION", "message": "Modification requires locators.", "context": {}}

                if error:
                    is_idempotency_skip = False
                    if action == 'DELETE' and error.get('code') in ['SNIPPET_NOT_FOUND', 'ANCHOR_NOT_FOUND']:
                        report_idempotency_skip("Snippet to delete is already gone."); is_idempotency_skip = True
                    if action == 'REPLACE' and error.get('code') in ['SNIPPET_NOT_FOUND', 'ANCHOR_NOT_FOUND', 'snippet_tail_NOT_FOUND']:
                        content_pos, _ = find_target_in_content(working_content, anchor_val, content_to_add or "", debug=False)
                        if content_pos: report_idempotency_skip("Snippet not found, but replacement content exists."); is_idempotency_skip = True

                    if is_idempotency_skip: continue

                    report = {"status": "FAILED", "file_path": relative_path, "mod_idx": mod_idx, "error": error}
                    if 'context' not in report['error']: report['error']['context'] = {}
                    report['error']['context']['action'] = action

                    if not strict:
                        failed_in_this_pass.append((mod_idx, mod, report, error, original_content))
                        continue
                    else:
                        if create_failure_case:
                            create_failure_case_file("afailed.log", report, original_content)
                        return report_error(report)

                if action == 'CREATE': continue
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

                if action == 'REPLACE' and normalize_block(working_content[start_pos:end_pos]) == normalize_block(content_to_add):
                    report_idempotency_skip("REPLACE content already present.")
                    last_mod_end_pos = end_pos
                    continue
                elif action == 'INSERT_AFTER' and normalize_block(working_content[end_pos:]).startswith(normalize_block(content_to_add)):
                    report_idempotency_skip("INSERT_AFTER content already present.")
                    last_mod_end_pos = end_pos + len(content_to_add or "")
                    continue
                elif action == 'INSERT_BEFORE' and normalize_block(working_content[:start_pos]).endswith(normalize_block(content_to_add)):
                    report_idempotency_skip("INSERT_BEFORE content already present.")
                    last_mod_end_pos = start_pos
                    continue

                if action == 'DELETE':
                    working_content = working_content[:start_pos] + working_content[end_pos:]

                indented_content = content_to_add or ""
                if action in ['REPLACE', 'INSERT_AFTER', 'INSERT_BEFORE'] and content_to_add:
                    def indent_warn(message, _idx=mod_idx):
                        if not silent: print(f"  [TOLERANT] Mod #{_idx + 1}: {message}")
                    indented_content = reindent_content(
                        working_content, start_pos, end_pos, content_to_add, action, strict, indent_warn)
                    debug_print(debug, "INDENTATION LOGIC", reindented=indented_content != content_to_add)
                    original_had_trailing_newline = end_pos > start_pos and working_content[end_pos-1] == internal_newline
                    if action in ['INSERT_AFTER', 'INSERT_BEFORE'] or (action == 'REPLACE' and original_had_trailing_newline):
                        if not indented_content.endswith('\n'):
                            indented_content += internal_newline

                if action == 'REPLACE':
                    working_content = working_content[:start_pos] + indented_content + working_content[end_pos:]
                elif action == 'INSERT_AFTER':
                    working_content = working_content[:end_pos] + indented_content + working_content[end_pos:]
                elif action == 'INSERT_BEFORE':
                    working_content = working_content[:start_pos] + indented_content + working_content[start_pos:]

                # Update cursor position for the next iteration based on the change that just happened.
                if action == 'REPLACE':
                    last_mod_end_pos = start_pos + len(indented_content)
                elif action == 'INSERT_AFTER':
                    last_mod_end_pos = end_pos + len(indented_content)
                elif action == 'INSERT_BEFORE':
                    last_mod_end_pos = start_pos + len(indented_content)
                elif action == 'DELETE':
                    last_mod_end_pos = start_pos

                made_progress = True
                if not silent:
                    pass_str = f" (Pass {pass_number})" if pass_number > 1 else ""
                    print(f"  + SUCCESS: Mod #{mod_idx + 1} ({action}) applied{pass_str}.")

            if not made_progress:
                final_failed_mods = failed_in_this_pass
                break

            pending_mods = [(idx, m) for idx, m, r, e, c in failed_in_this_pass]
            pass_number += 1

        if final_failed_mods:
            llm_file_reports.append({
                "file_path": relative_path,
                "original": original_content.replace('\r\n', internal_newline).replace('\r', internal_newline),
                "current": working_content,
                "total_mods": len(change.get('modifications', [])),
                "failed": [{"mod_idx": mi, "mod": m, "error": e} for mi, m, r, e, c in final_failed_mods],
            })

        for mod_idx, mod, report, err_dict, orig_content in final_failed_mods:
            if not silent:
                print(f"  - FAILED: Mod #{mod_idx + 1} ({mod.get('action') or 'Unknown'}). Reason: {err_dict.get('message')}")
            if create_failure_case:
                create_failure_case_file(f"afailed.{mod_idx}.log", report, orig_content)

            failed_file_block = next((item for item in failed_changes_output if item.get('file_path') == relative_path), None)
            if not failed_file_block:
                failed_file_block = {'file_path': relative_path, 'modifications': []}
                if change.get('newline'): failed_file_block['newline'] = change.get('newline')
                failed_changes_output.append(failed_file_block)

            failed_file_block['modifications'].append(mod)

        if not terminal_op_planned:
            final_content = newline_char.join([line for line in working_content.split(internal_newline)])
            if final_content != original_content or not file_existed:
                write_plan.append(('WRITE', file_path, final_content, relative_path, original_content))

    if not strict and failed_changes_output:
        afailed_path = os.path.join(project_dir, "afailed.ap")
        with open(afailed_path, "w", encoding="utf-8") as f:
            f.write(f"# Summary: Failed changes from a tolerant patch application.\n\n")
            f.write(f"{patch_id_str} AP {AP_FORMAT_VERSION}\n\n")
            for change_item in failed_changes_output:
                f.write(f"{patch_id_str} FILE")
                if change_item.get("newline"): f.write(f" {change_item['newline']}")
                f.write(f"\n{change_item['file_path']}\n\n")
                for mod_item in change_item['modifications']:
                    f.write(f"{patch_id_str} {mod_item['action']}\n")
                    for key in ['anchor', 'snippet', 'snippet_tail', 'content']:
                        if key in mod_item: f.write(f"{patch_id_str} {key}\n{mod_item[key]}\n")
                    for key in ['include_leading_blank_lines', 'include_trailing_blank_lines']:
                        if key in mod_item: f.write(f"{patch_id_str} {key} {mod_item[key]}\n")
                    f.write("\n")
        write_llm_report(afailed_md_path, patch_content, llm_file_reports)
        if not silent:
            print(f"\nWARNING: Some changes failed and were written to {afailed_path}")
            print(f"         A briefing for the generating model is in {afailed_md_path}")

    if not dry_run:
        # Separate operations into phases to avoid conflicts (e.g., delete before create)
        delete_ops = [op for op in write_plan if op[0] == 'DELETE_PATH']
        rename_ops = [op for op in write_plan if op[0] == 'RENAME']
        create_dir_ops = [op for op in write_plan if op[0] == 'CREATE_DIR']
        write_ops = [op for op in write_plan if op[0] == 'WRITE']

        # Phase 1: Deletions
        for _, path_to_delete, _, r_path in delete_ops:
            try:
                debug_print(debug, "DELETING", path=path_to_delete)
                if os.path.isfile(path_to_delete):
                    os.remove(path_to_delete)
                elif os.path.isdir(path_to_delete):
                    shutil.rmtree(path_to_delete)
            except (IOError, OSError) as e:
                err_details = {"status": "FAILED", "file_path": r_path, "error": {"code": "FILE_DELETE_ERROR", "message": str(e)}}
                if create_failure_case: create_failure_case_file("afailed.log", err_details, None)
                return report_error(err_details)

        # Phase 2: Renames
        for _, old_path, new_path, r_path in rename_ops:
            try:
                debug_print(debug, "RENAMING", old=old_path, new=new_path)
                # For idempotency, source might already be gone if destination exists
                if os.path.exists(old_path):
                    os.makedirs(os.path.dirname(new_path) or '.', exist_ok=True)
                    os.rename(old_path, new_path)
            except OSError as e:
                err_details = {"status": "FAILED", "file_path": r_path, "error": {"code": "FILE_RENAME_ERROR", "message": str(e)}}
                if create_failure_case: create_failure_case_file("afailed.log", err_details, None)
                return report_error(err_details)

        # Phase 3: Directory Creations
        for _, path_to_create, _, r_path in create_dir_ops:
            try:
                debug_print(debug, "CREATING DIR", path=path_to_create)
                os.makedirs(path_to_create, exist_ok=True)
            except OSError as e:
                err_details = {"status": "FAILED", "file_path": r_path, "error": {"code": "DIR_CREATE_ERROR", "message": str(e)}}
                if create_failure_case: create_failure_case_file("afailed.log", err_details, None)
                return report_error(err_details)

        # Phase 4: File Writes
        for _, f_path, f_content, r_path, _prev in write_ops:
            try:
                debug_print(debug, "WRITING FILE", path=f_path, content_len=len(f_content))
                os.makedirs(os.path.dirname(f_path) or '.', exist_ok=True)
                # Always use newline='' to prevent translation. The newline_char has already been
                # determined (either from spec or detection) and is baked into the f_content string.
                with open(f_path, 'w', encoding='utf-8', newline='') as f: f.write(f_content)
            except IOError as e:
                err_details = {"status": "FAILED", "file_path": r_path, "error": {"code": "FILE_WRITE_ERROR", "message": str(e)}}
                if create_failure_case:
                    create_failure_case_file("afailed.log", err_details, original_content if 'original_content' in locals() else None)
                return report_error(err_details)

    elif write_plan:
        debug_print(debug, "DRY RUN: SKIPPING WRITE", num_files=len(write_plan))
        if not silent and not json_report:
            print("\n--- DRY RUN: planned changes ---")
            for op in write_plan:
                kind, path_a, payload, r_path = op[0], op[1], op[2], op[3]
                if kind == 'WRITE':
                    before = (op[4] if len(op) > 4 else "") or ""
                    diff = difflib.unified_diff(
                        before.splitlines(keepends=True),
                        (payload or "").splitlines(keepends=True),
                        fromfile=f"a/{r_path}", tofile=f"b/{r_path}")
                    body = "".join(diff)
                    print(body if body else f"(no textual change) {r_path}")
                elif kind == 'RENAME':
                    print(f"rename {r_path} -> {os.path.relpath(payload or path_a, project_dir)}")
                else:
                    print(f"{kind.lower().replace('_', ' ')} {r_path}")
    else:
        debug_print(debug, "NO CHANGES: SKIPPING WRITE")
        pass

    if not failed_changes_output and not dry_run and os.path.exists(afailed_md_path):
        try: os.remove(afailed_md_path)
        except OSError: pass

    if failed_changes_output:
        return {"status": "PARTIAL", "failed_files": [c.get('file_path') for c in failed_changes_output]}
    return {"status": "SUCCESS"}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Apply an AI-friendly Patch (ap) file.")
    parser.add_argument("patch_file", help="Path to the .ap patch file.")
    parser.add_argument("--dir", default=".", help="The root directory of the source code.")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without modifying files.")
    parser.add_argument("-s", "--strict", action="store_true", help="Run in strict mode (enforce atomicity, 8-hex ID, no drift).")
    parser.add_argument("--json-report", action="store_true", help="Output machine-readable JSON on failure.")
    parser.add_argument("--failure-report", help="Path to save a detailed JSON report on failure (includes context).")
    parser.add_argument("--create-failure-case", action="store_true", help="On failure, create afailed.log (or afailed.<mod_idx>.log in tolerant mode) with full context for debugging.")
    parser.add_argument("--debug", action="store_true", help="Enable detailed debug logging.")
    parser.add_argument("--no-final-newline", action="store_true", help="Do not append a trailing newline to rewritten files.")
    parser.add_argument("-v", "--version", action="version", version=f"ap patcher {AP_FORMAT_VERSION}")

    args = parser.parse_args()
    result = apply_patch(args.patch_file, args.dir, args.dry_run, args.json_report, args.debug,
                         args.strict, args.failure_report, args.create_failure_case,
                         ensure_final_newline=not args.no_final_newline)

    if args.json_report and result['status'] != 'SUCCESS':
        print(json.dumps(result, indent=2))

    # 0 = everything applied, 2 = tolerant run with skipped modifications
    # (see afailed.ap), 1 = nothing was applied.
    if result["status"] == "PARTIAL":
        exit(2)
    if result["status"] != "SUCCESS":
        exit(1)