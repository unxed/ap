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
ARG_KEYS = {'include_leading_blank_lines', 'include_trailing_blank_lines', 'scope_end'}
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
    'whole_block': 'scope_end', 'block_end': 'scope_end', 'to_scope_end': 'scope_end',
}

# Prefixes that a model may prepend to the first line of a quoted code block
# without changing its meaning: indentation, comment openers, bullets, diff
# markers and list numbering. Anything containing identifier characters is a
# real part of the line and MUST NOT be dropped by the suffix heuristic.
DECORATION_PREFIX_RE = re.compile(r'^[\s#/*>+\-\u2022\u00b7\[\]().\d]*$')

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
    inside_fenced_block = False

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
    include_dir = r'((?:include_leading_blank_lines|include_trailing_blank_lines|scope_end)(?:\s+\d+)?)'
    drift_pattern = re.compile(rf'^(\S+)\s+({paramless}|{file_dir}|{include_dir})$')

    def flush_value(at_eof: bool = False):
        """Commits the collected value block to the directive that opened it."""
        nonlocal current_file_change, current_modification, reading_key, value_lines, pending_args
        if not reading_key:
            return
        # A value block closed by the END of the file is the one place where an
        # empty block is ambiguous: it may be deliberate, or the answer may have
        # been cut off mid-generation. A block closed by a following directive is
        # provably complete. Recording which one it was lets the patcher accept
        # deliberate emptiness and still refuse truncated patches.
        if at_eof and current_modification is not None and reading_key in VALUE_KEYS:
            current_modification['_eof_value'] = reading_key
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
        if FENCE_RE.match(line):
            inside_fenced_block = not inside_fenced_block

        id_drift_match = None if inside_fenced_block else drift_pattern.match(stripped_line)
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
                    if key == 'scope_end':
                        # A flag, not a count: accept it with or without the `1`.
                        current_modification[key] = 1
                        continue
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

    flush_value(at_eof=True)

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
            # HYBRID SEARCH: first line is matched as a suffix, the rest exactly.
            first_line_match = normalized_content_lines[0].endswith(normalized_snippet_lines[0])
            # The suffix relaxation exists to absorb non-semantic decoration a
            # model prepends to the first line of a quoted block (list numbering,
            # bullets, comment markers, diff signs). Unrestricted, it accepts
            # `self.count = 0` for the locator `count = 0` and REPLACE then
            # destroys the `self.` prefix - a silent corruption, not a failed
            # match. So the dropped prefix has to look like decoration.
            if (first_line_match
                    and len(normalized_content_lines[0]) != len(normalized_snippet_lines[0])):
                dropped = normalized_content_lines[0][:-len(normalized_snippet_lines[0])]
                first_line_match = bool(DECORATION_PREFIX_RE.match(dropped))
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

# --- Structural awareness --------------------------------------------------
# The patcher cannot parse every language, but a bracket counter that skips
# strings and comments is enough to answer the two questions that cause most
# structurally broken output: "am I about to insert top-level code inside a
# block?" and "where does the block opened by this snippet end?".

_LINE_COMMENTS = ('//', '#', '--')

# Words that open a declaration (the thing that lives at file scope) versus
# words that open a control-flow or closure block (the thing that legitimately
# lives inside another block).
DECLARATION_KEYWORDS = {
    'func', 'function', 'def', 'class', 'struct', 'interface', 'enum', 'impl',
    'trait', 'type', 'fn', 'namespace', 'module', 'package', 'const', 'let',
    'var', 'export', 'public', 'private', 'protected', 'static', 'abstract',
    'template', 'record', 'object', 'proc', 'sub',
}
CONTROL_KEYWORDS = {
    'if', 'else', 'elif', 'for', 'foreach', 'while', 'switch', 'case', 'do',
    'try', 'catch', 'except', 'finally', 'go', 'defer', 'select', 'with',
    'match', 'when', 'return', 'loop', 'unless', 'repeat',
}

def line_start_depths(content: str, clamp: bool = True) -> Tuple[List[int], List[int]]:
    """
    Returns (line start offsets, bracket nesting depth at each line start).

    String literals, line comments and /* */ blocks are skipped so that braces
    inside them do not distort the depth.
    """
    starts: List[int] = [0]
    depths: List[int] = [0]
    depth = 0
    in_string: Optional[str] = None
    in_block_comment = False
    escaped = False
    i, n = 0, len(content)
    line_comment = False
    while i < n:
        ch = content[i]
        if ch == '\n':
            line_comment = False
            if in_string in ("'", '"'):
                in_string = None  # unterminated quote: do not swallow the rest of the file
            escaped = False
            starts.append(i + 1)
            depths.append(depth)
            i += 1
            continue
        if in_block_comment:
            if ch == '*' and content.startswith('*/', i):
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if in_string:
            if escaped:
                escaped = False
            elif ch == '\\':
                escaped = True
            elif ch == in_string:
                in_string = None
            i += 1
            continue
        if line_comment:
            i += 1
            continue
        if content.startswith('/*', i):
            in_block_comment = True
            i += 2
            continue
        if any(content.startswith(c, i) for c in _LINE_COMMENTS):
            line_comment = True
            i += 1
            continue
        if ch in ('"', "'", '`'):
            in_string = ch
        elif ch in '([{':
            depth += 1
        elif ch in ')]}':
            # Clamping keeps the per-line depths usable for block scanning even
            # in files with stray closers; the balance check needs the raw count,
            # otherwise an extra `}` is invisible.
            depth = max(0, depth - 1) if clamp else depth - 1
        i += 1
    if starts[-1] != n:
        pass
    return starts, depths

def net_bracket_depth(text: str) -> int:
    """Bracket balance of a whole text, ignoring strings and comments."""
    _, depths = line_start_depths(text + '\n', clamp=False)
    return depths[-1] if depths else 0

def line_index_at(starts: List[int], offset: int) -> int:
    lo, hi = 0, len(starts) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if starts[mid] <= offset:
            lo = mid
        else:
            hi = mid - 1
    return lo

def indent_width(line: str) -> int:
    return len(line) - len(line.lstrip(' \t'))

def resolve_scope_end(content: str, start_pos: int, end_pos: int) -> Optional[int]:
    """
    Extends a located region to the end of the block its snippet opens.

    Brace languages are handled by nesting depth; indentation languages by the
    indent of the snippet's first line. Returns None when the snippet does not
    open a block at all.
    """
    starts, depths = line_start_depths(content)
    lines = content.split('\n')
    i0 = line_index_at(starts, start_pos)
    i1 = line_index_at(starts, max(end_pos - 1, start_pos))
    base_depth = depths[i0]
    depth_after = depths[i1 + 1] if i1 + 1 < len(depths) else base_depth

    if depth_after > base_depth:
        for j in range(i1 + 1, len(starts)):
            if depths[j] <= base_depth:
                return starts[j]
        return len(content)

    # Indentation languages: the block is everything indented deeper than the
    # snippet's first line.
    base_indent = indent_width(lines[i0])
    opener = lines[i1].rstrip()
    if not opener.endswith(':'):
        return None
    for j in range(i1 + 1, len(lines)):
        if not lines[j].strip():
            continue
        if indent_width(lines[j]) <= base_indent:
            return starts[j]
    return len(content)

def top_level_insert_correction(content: str, pos: int, new_content: str, after: bool) -> Optional[int]:
    """
    Detects the single most damaging insertion mistake: a self-contained
    top-level declaration inserted between a declaration line and the body it
    opens, producing `func A() {` / `func B() {` / `}` / `}`.

    Returns the corrected offset, or None if the insertion point is fine.
    Deliberately limited to brace languages: for indentation languages a
    column-0 `content` is far more often a dropped indent (already handled by
    reindent_content) than a misplaced top-level block.
    """
    body = [l for l in (new_content or '').split('\n') if l.strip()]
    if not body or indent_width(body[0]) > 0:
        return None
    starts, depths = line_start_depths(content)
    idx = line_index_at(starts, pos)
    if depths[idx] <= 0:
        return None
    # The inserted block must be self-contained, otherwise it really does belong
    # inside the enclosing block.
    # Trailing newline forces a final entry, so inner[-1] is the net depth of
    # the whole block rather than the depth at its last line.
    _, inner = line_start_depths(new_content + '\n')
    if inner and inner[-1] != 0:
        return None
    # `content` must itself open a block. A bare statement at column 0 is a
    # dropped indent (reindent_content's job), not a misplaced declaration -
    # moving it out of the enclosing block would be the worse error.
    if not inner or max(inner) == 0:
        return None
    # ... and it must look like a DECLARATION. A nested closure or a control
    # block written at column 0 is also self-contained, but it genuinely belongs
    # where the model put it.
    head = body[0].strip()
    token = re.match(r'[A-Za-z_@#][\w]*', head)
    if not token:
        return None
    if token.group(0) in CONTROL_KEYWORDS:
        return None
    if token.group(0) not in DECLARATION_KEYWORDS and not head.rstrip().endswith(('{', ':')):
        return None
    if after:
        for j in range(idx, len(starts)):
            if depths[j] == 0:
                return starts[j]
        return len(content)
    for j in range(idx, -1, -1):
        if depths[j] == 0:
            return starts[j]
    return 0

def line_number_at(content: str, offset: int) -> int:
    return content.count('\n', 0, offset) + 1

def shift_dirty(dirty: List[Tuple[int, int]], start: int, end: int, new_len: int) -> List[Tuple[int, int]]:
    """
    Keeps the `dirty` map valid after an edit replaced [start, end) with new_len chars.

    Regions before the edit keep their offsets, regions after it slide by the
    length delta, and regions the edit overwrote are dropped - the newly written
    span replaces them.
    """
    delta = new_len - (end - start)
    updated = []
    for a, b in dirty:
        if b <= start:
            updated.append((a, b))
        elif a >= end:
            updated.append((a + delta, b + delta))
        # else: overwritten by this edit, drop it.
    if new_len > 0:
        updated.append((start, start + new_len))
    return sorted(updated)

def is_dirty(span: Tuple[int, int], dirty: List[Tuple[int, int]]) -> bool:
    """True if `span` lies entirely inside text this patch run wrote itself."""
    return any(a <= span[0] and span[1] <= b for a, b in dirty)

def find_target_in_content(content: str, anchor: Optional[str], snippet: str, debug: bool = False, last_match_end: int = 0, allow_repeat: bool = False, dirty: Optional[List[Tuple[int, int]]] = None, dirty_strict: bool = False) -> Tuple[Optional[Tuple[int, int]], Dict[str, Any]]:
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

        # An anchor duplicated by this patch's own output is not a real second
        # anchor. Filtering here turns a spurious AMBIGUOUS_ANCHOR back into a
        # clean resolution; the fallback keeps anchors that only exist in
        # freshly written code usable.
        if dirty:
            clean_anchors = [a for a in anchor_occurrences if not is_dirty(a, dirty)]
            if clean_anchors:
                anchor_occurrences = clean_anchors

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

    # === SELF-WRITTEN TEXT FILTER ===
    # A locator must never resolve against text this very patch run has just
    # inserted, otherwise a later modification silently patches the output of an
    # earlier one (or an idempotency probe finds its own replacement content and
    # reports "already applied"). The cursor alone cannot express this: it is a
    # scalar, while the regions we wrote are a set of intervals.
    if dirty and occurrences:
        clean = [o for o in occurrences if not is_dirty((o[0] + offset, o[1] + offset), dirty)]
        if clean:
            occurrences = clean
        elif dirty_strict:
            # Probes (idempotency) must not fall back: matching our own output is
            # exactly the false positive we are guarding against.
            occurrences = []
        else:
            debug_print(debug, "DIRTY FALLBACK",
                        message="All matches lie in text written by this patch; using them anyway.")

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
    "LOCATOR_CONSUMED":
        "The locator was present in the original file, but an earlier modification in THIS patch "
        "replaced or deleted the region containing it. Do not restate a change you have already "
        "made: fold the second edit into the `content` of the first one, or rewrite its locator "
        "against the text as it looks AFTER the earlier modification.",
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
        "`REPLACE` with empty `content` is refused in strict mode. Use `DELETE` to remove code.",
    "PATCH_TRUNCATED":
        "The patch file ends with an empty `content` block, which is what a cut-off answer looks "
        "like. Re-emit the patch in full. Appending an `[ID] END` directive proves the patch is "
        "complete and makes a deliberately empty `content` acceptable.",
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
    label = f" {lang.upper()}" if lang else ""
    return f"--- BEGIN{label} ---\n{body}--- END{label} ---\n"


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
            top_part = parts[0]
            # Only attempt prefix stripping if the leading directory does NOT exist in project_dir.
            # If the leading directory exists (e.g. "bindings" in "bindings/python/README.md"),
            # the path is already correctly anchored and must not be stripped!
            if len(parts) > 1 and not os.path.exists(os.path.join(project_dir, top_part)):
                found = False
                for i in range(1, len(parts)):
                    test_path = '/'.join(parts[i:])
                    if os.path.exists(os.path.join(project_dir, test_path)):
                        relative_path = test_path
                        stripped_prefix = '/'.join(parts[:i])
                        found = True
                        break

                # If the file does not exist, check if a subdirectory inside the remaining path exists,
                # while the leading prefix does not.
                if not found:
                    for i in range(1, len(parts)):
                        prefix_parts = parts[:i]
                        prefix_path = os.path.join(project_dir, *prefix_parts)
                        target_dir_path = os.path.join(project_dir, parts[i])
                        if not os.path.exists(prefix_path) and os.path.isdir(target_dir_path):
                            relative_path = '/'.join(parts[i:])
                            stripped_prefix = '/'.join(parts[:i])
                            found = True
                            break

                if not found:
                    project_dir_abs = os.path.abspath(project_dir).replace('\\', '/')
                    project_dir_name = os.path.basename(project_dir_abs)
                    for i in range(len(parts) - 1, 0, -1):
                        prefix = '/'.join(parts[:i])
                        if (project_dir_abs.endswith('/' + prefix) or
                            project_dir_abs == prefix or
                            (len(prefix) >= 2 and (project_dir_name.startswith(prefix) or prefix.startswith(project_dir_name)))):
                            relative_path = '/'.join(parts[i:])
                            stripped_prefix = prefix
                            found = True
                            break

            if not found:
                project_dir_abs = os.path.abspath(project_dir).replace('\\', '/')
                project_dir_name = os.path.basename(project_dir_abs)
                for i in range(len(parts) - 1, 0, -1):
                    prefix = '/'.join(parts[:i])
                    if (project_dir_abs.endswith('/' + prefix) or
                        project_dir_abs == prefix or
                        (len(prefix) >= 2 and (project_dir_name.startswith(prefix) or prefix.startswith(project_dir_name)))):
                        relative_path = '/'.join(parts[i:])
                        stripped_prefix = prefix
                        found = True
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
        if len(mods) == 1 and mods[0].get('action') == 'DELETE' and not (set(mods[0]) - {'action', '_line', '_eof_value'}):
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
        # Snapshot + log of what each modification consumed. When a later locator
        # cannot be found, this is what turns "Snippet not found" into "your own
        # modification #k deleted it".
        initial_content = working_content
        consumed_log: List[Tuple[int, str]] = []
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

        # Spans of `working_content` that this patch run wrote itself. Unlike the
        # cursor it survives across retry passes, so a modification retried with
        # a reset cursor still cannot latch onto the output of its predecessors.
        dirty_regions: List[Tuple[int, int]] = []

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
                    elif action in ('REPLACE', 'RECREATE') and not content_to_add:
                        # An empty `content` is only dangerous when it might be the
                        # tail of a truncated answer. If a directive follows it in
                        # the patch file, the emptiness is provably deliberate, and
                        # `REPLACE` with nothing is simply a `DELETE`, which is what
                        # models write anyway.
                        truncated = mod.get('_eof_value') == 'content'
                        if truncated or strict:
                            code = "PATCH_TRUNCATED" if truncated else "EMPTY_REPLACE"
                            msg = ("The patch ends with an empty 'content' block, so it cannot be "
                                   "told apart from a truncated answer. Finish the patch, or close "
                                   "it with an 'END' directive."
                                   if truncated else
                                   f"{action} with empty content is not allowed in strict mode. Use DELETE instead.")
                            error = {"code": code, "message": msg, "context": {}}
                            report = {"status": "FAILED", "file_path": relative_path, "mod_idx": mod_idx, "error": error}
                            if not strict:
                                failed_in_this_pass.append((mod_idx, mod, report, error, original_content))
                                continue
                            else:
                                if create_failure_case:
                                    create_failure_case_file("afailed.log", report, original_content)
                                return report_error(report)
                        if action == 'REPLACE':
                            action = 'DELETE'
                            content_to_add = None
                            if not silent:
                                print(f"  [TOLERANT] Mod #{mod_idx + 1}: empty 'content'; "
                                      f"treating REPLACE as DELETE.")

                if action == 'RECREATE':
                    if working_content == (content_to_add or ""):
                        report_idempotency_skip("RECREATE content already matches.")
                        continue
                    working_content = content_to_add or ""
                    dirty_regions = [(0, len(working_content))] if working_content else []
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
                            start_pos_info, error = find_target_in_content(working_content, anchor_val, snippet_val, debug, last_mod_end_pos, allow_repeat, dirty_regions)
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
                     target_pos, error = find_target_in_content(working_content, anchor_val, snippet_val, debug, last_mod_end_pos, allow_repeat, dirty_regions)

                elif action != 'CREATE':
                    error = {"code": "INVALID_MODIFICATION", "message": "Modification requires locators.", "context": {}}

                if error:
                    is_idempotency_skip = False
                    if action == 'DELETE' and error.get('code') in ['SNIPPET_NOT_FOUND', 'ANCHOR_NOT_FOUND']:
                        report_idempotency_skip("Snippet to delete is already gone."); is_idempotency_skip = True
                    if action == 'REPLACE' and error.get('code') in ['SNIPPET_NOT_FOUND', 'ANCHOR_NOT_FOUND', 'snippet_tail_NOT_FOUND']:
                        content_pos, _ = find_target_in_content(
                            working_content, anchor_val, content_to_add or "", debug=False,
                            dirty=dirty_regions, dirty_strict=True)
                        if content_pos: report_idempotency_skip("Snippet not found, but replacement content exists."); is_idempotency_skip = True

                    if is_idempotency_skip: continue

                    # === WAS THE LOCATOR CONSUMED BY THIS VERY PATCH? ===
                    # Overlapping modifications are a routine generation error:
                    # #1 replaces a block, #2 targets a line that lived inside it.
                    # "Snippet not found" sends the model looking for a phantom
                    # change in the file; naming the culprit modification lets it
                    # merge the two instead of guessing.
                    if error.get('code') in ('SNIPPET_NOT_FOUND', 'ANCHOR_NOT_FOUND', 'snippet_tail_NOT_FOUND'):
                        probe = {'ANCHOR_NOT_FOUND': anchor_val,
                                 'snippet_tail_NOT_FOUND': snippet_tail}.get(error['code'], snippet_val)
                        culprit = None
                        if probe:
                            for c_idx, removed in consumed_log:
                                if c_idx != mod_idx and removed and smart_find(removed, probe):
                                    culprit = c_idx
                                    break
                            if (culprit is None and smart_find(initial_content, probe)
                                    and not smart_find(working_content, probe)):
                                culprit = -1
                        if culprit is not None:
                            where = (f"modification #{culprit + 1}" if culprit >= 0
                                     else "an earlier modification")
                            error = {
                                "code": "LOCATOR_CONSUMED",
                                "message": (f"The locator existed in the original file but {where} of the "
                                            f"same file removed it. Modifications are applied in order, "
                                            f"each seeing the result of the previous ones."),
                                "context": {"snippet": snippet_val, "anchor": anchor_val,
                                            "removed_by_mod": culprit + 1 if culprit >= 0 else None},
                            }

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

                # === SCOPE EXPANSION ===
                # `scope_end` lets a locator name a construct by its header line
                # alone: the region is extended to the end of the block that
                # header opens. This removes the need for a snippet/snippet_tail
                # pair when replacing or deleting a whole function, and makes
                # "insert after function A" expressible without guessing where A
                # ends.
                if mod.get('scope_end'):
                    expanded = resolve_scope_end(working_content, start_pos, end_pos)
                    if expanded is None:
                        if not silent:
                            print(f"  [TOLERANT] Mod #{mod_idx + 1}: 'scope_end' requested but the "
                                  f"snippet does not open a block; ignoring it.")
                    else:
                        end_pos = max(end_pos, expanded)

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

                # === NESTING GUARD ===
                # A model asked to add a function "after function A" reaches for
                # A's signature line as the locator, which places the new
                # function between the signature and its body. The result is
                # syntactically broken but applies cleanly, so nothing catches it
                # until the compiler does.
                if action in ('INSERT_AFTER', 'INSERT_BEFORE') and content_to_add:
                    probe = end_pos if action == 'INSERT_AFTER' else start_pos
                    corrected = top_level_insert_correction(
                        working_content, probe, content_to_add, action == 'INSERT_AFTER')
                    if corrected is not None and corrected != probe:
                        if strict:
                            error = {"code": "NESTING_MISMATCH",
                                     "message": (f"'{action}' would place a self-contained top-level block "
                                                 f"inside another block. Use a locator on the surrounding "
                                                 f"declaration with 'scope_end 1', or target the neighbouring "
                                                 f"top-level declaration instead."),
                                     "context": {"snippet": snippet_val}}
                            report = {"status": "FAILED", "file_path": relative_path, "mod_idx": mod_idx, "error": error}
                            if create_failure_case:
                                create_failure_case_file("afailed.log", report, original_content)
                            return report_error(report)
                        if not silent:
                            print(f"  [TOLERANT] Mod #{mod_idx + 1}: insertion point is inside a block while "
                                  f"'content' is a self-contained top-level block; "
                                  f"moving it to the {'end' if action == 'INSERT_AFTER' else 'start'} "
                                  f"of the enclosing block.")
                        # Keep the blank line that separates top-level
                        # declarations: `content` is trimmed of blank lines, so it
                        # has to be re-added here.
                        needs_pad = (corrected >= 2 and working_content[corrected - 1] == '\n'
                                     and working_content[corrected - 2] != '\n')
                        if action == 'INSERT_AFTER':
                            end_pos = corrected
                            start_pos = min(start_pos, end_pos)
                            if needs_pad:
                                content_to_add = '\n' + content_to_add
                        else:
                            start_pos = corrected
                            end_pos = max(end_pos, start_pos)
                            if corrected > 0 and not working_content[:corrected].endswith('\n\n'):
                                content_to_add = content_to_add + '\n'

                if action == 'REPLACE' and normalize_block(working_content[start_pos:end_pos]) == normalize_block(content_to_add):
                    report_idempotency_skip("REPLACE content already present.")
                    last_mod_end_pos = end_pos
                    continue
                elif action == 'INSERT_AFTER' and normalize_block(working_content[end_pos:]).startswith(normalize_block(content_to_add)):
                    report_idempotency_skip("INSERT_AFTER content already present.")
                    # Advance the cursor past the copy that is ALREADY IN THE FILE.
                    # Using len(content_to_add) instead measures the patch's own
                    # formatting: when the file's copy is indented differently the
                    # cursor lands mid-construct and the next modification loses
                    # its target for no visible reason.
                    already_there = smart_find(working_content[end_pos:], content_to_add or "")
                    last_mod_end_pos = (end_pos + already_there[0][1]) if already_there else end_pos
                    continue
                elif action == 'INSERT_BEFORE' and normalize_block(working_content[:start_pos]).endswith(normalize_block(content_to_add)):
                    report_idempotency_skip("INSERT_BEFORE content already present.")
                    last_mod_end_pos = start_pos
                    continue

                if action in ('REPLACE', 'DELETE') and end_pos > start_pos:
                    consumed_log.append((mod_idx, working_content[start_pos:end_pos]))

                if action == 'DELETE':
                    working_content = working_content[:start_pos] + working_content[end_pos:]
                    dirty_regions = shift_dirty(dirty_regions, start_pos, end_pos, 0)

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
                    dirty_regions = shift_dirty(dirty_regions, start_pos, end_pos, len(indented_content))
                elif action == 'INSERT_AFTER':
                    working_content = working_content[:end_pos] + indented_content + working_content[end_pos:]
                    dirty_regions = shift_dirty(dirty_regions, end_pos, end_pos, len(indented_content))
                elif action == 'INSERT_BEFORE':
                    working_content = working_content[:start_pos] + indented_content + working_content[start_pos:]
                    dirty_regions = shift_dirty(dirty_regions, start_pos, start_pos, len(indented_content))

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

        # === STRUCTURAL SANITY CHECK ===
        # The patcher cannot parse the target language, but it can count
        # brackets. A file whose brackets balanced before the patch and do not
        # balance after it is almost always the result of a locator that cut a
        # construct in half - the patch applied cleanly and the code does not
        # compile. Reported as a warning, not a failure: the count is heuristic
        # and plenty of legitimate text files are unbalanced by nature.
        if file_existed and working_content != initial_content and not silent:
            before = net_bracket_depth(initial_content)
            after = net_bracket_depth(working_content)
            if before == 0 and after != 0:
                print(f"  ! WARNING: brackets in {relative_path} were balanced before the patch "
                      f"and are off by {after:+d} after it. The result is very likely not valid "
                      f"source code - review it before committing.")

        if not terminal_op_planned:
            final_content = newline_char.join([line for line in working_content.split(internal_newline)])
            if final_content != original_content or not file_existed:
                # A file that ends without a newline produces a noisy diff for
                # whoever edits its last line next, so every file this patcher
                # rewrites gets one. Only files it actually changed: silently
                # appending a newline to an otherwise untouched file would be
                # exactly the spurious diff this avoids elsewhere.
                if final_content and not final_content.endswith(newline_char):
                    final_content += newline_char
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
                    for key in ['include_leading_blank_lines', 'include_trailing_blank_lines', 'scope_end']:
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
    parser.add_argument("-v", "--version", action="version", version=f"ap patcher {AP_FORMAT_VERSION}")

    args = parser.parse_args()
    result = apply_patch(args.patch_file, args.dir, args.dry_run, args.json_report, args.debug,
                         args.strict, args.failure_report, args.create_failure_case)

    if args.json_report and result['status'] != 'SUCCESS':
        print(json.dumps(result, indent=2))

    # 0 = everything applied, 2 = tolerant run with skipped modifications
    # (see afailed.ap), 1 = nothing was applied.
    if result["status"] == "PARTIAL":
        exit(2)
    if result["status"] != "SUCCESS":
        exit(1)
