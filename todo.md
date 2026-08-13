# Outstanding Design Questions & Deferred Tasks

This file documents deferred improvements, potential bugs, and architectural concerns
for the `ap` patcher and specification.

## 1. Trailing Newlines in Rewritten Files
- **Status**: Completed.
- **Context**: `ap.md` §4.5 stated that the reference patcher always ends output files with a newline. It did not: `a\nb` patched to `a\nB` stayed newline-less, so the spec described behaviour that did not exist. The `--update-expected` flag this item depended on had also never actually been added to `run_tests.py`.
- **Implementation**: `--update-expected` implemented (it rewrites fixtures in `expected/` from the current output and prints a reminder to review `git diff`, since it turns every regression into a passing test). The newline policy is applied only to files the patcher actually changed - appending a newline to an otherwise untouched file would be precisely the spurious diff the policy exists to prevent - and uses the file's own line ending, so CRLF files get `\r\n`. 37 fixtures regenerated, 2 inline expectations in `cases.py` updated by hand.

## 2. Hybrid Search Suffix-Matching for Single-line Locators
- **Status**: Completed.
- **Context**: The suffix relaxation of `smart_find` applied to single-line locators too, so `count = 0` matched `self.count = 0` and `REPLACE` silently destroyed the `self.` prefix. Reported as a matching quirk, but it is data corruption: the patch applies and reports SUCCESS.
- **Implementation**: The relaxation now requires the dropped prefix to consist only of decoration (whitespace, comment openers, bullets, diff markers, list numbering). `24_heuristics` keeps passing because `# 1. ` is decoration, while `self.` is not.

## 3. Redundant Project Directory Prefix in File Paths
- **Status**: Completed.
- **Context**: LLM code generators sometimes prefix file paths with the project/repository directory name (e.g. `my_project/src/file.py`), depending on whether they assume the patch will be applied from inside or outside the project folder.
- **Implementation**: Added a dual heuristic in `ap.py` to automatically detect and strip redundant prefixes.
  1. For existing files, it strips any prefix that leads to a valid file path on disk.
  2. For newly created files/folders, it checks if a subdirectory inside the remaining path exists while the leading prefix does not (e.g. `src` exists, but `my_project` does not).
  3. If none of the above matches, it checks if the prefix has a starts/endswith relationship with the parent project folder name (length >= 2).

## 4. Self-Written Text Must Not Be Matchable
- **Status**: Completed.
- **Context**: The only protection against a modification latching onto the output of an earlier one was the scalar cursor `last_mod_end_pos`, which is reset to 0 on every retry pass. Two concrete failures followed:
  1. The `REPLACE` idempotency probe searched the whole file for `content` and found the copy the *previous* modification had just written, reporting "already applied" and dropping a requested change silently, with a SUCCESS exit code.
  2. A modification retried on pass 2 saw both the original text and the patch's own insertion, and failed with `AMBIGUOUS_MATCH` where the intent was unambiguous.
- **Implementation**: `dirty_regions` tracks every span this run wrote, is remapped after each edit (`shift_dirty`), and survives retry passes. `find_target_in_content` drops matches lying entirely inside those spans; the idempotency probe does so with no fallback (`dirty_strict`).

## 5. Anchors Are Not Yet Dirty-Filtered
- **Status**: Completed.
- **Context**: The self-written-text filter covered `snippet` searches and the idempotency probe but not `anchor` resolution, so an anchor duplicated by the patch's own output produced a spurious `AMBIGUOUS_ANCHOR`.
- **Implementation**: `dirty_regions` is now consulted in the anchor branch of `find_target_in_content`, with a fallback so that anchors existing only inside freshly written code remain usable.

## 6. Hybrid Search Suffix-Matching for the First Line of Multi-line Locators
- **Status**: Completed.
- **Context**: Item 2 restricted the suffix relaxation for single-line locators only; the same corruption was possible on the first line of a multi-line locator.
- **Implementation**: `DECORATION_PREFIX_RE` now gates the relaxation for every locator, single- or multi-line. The special case for single-line locators is gone: one rule covers both.

## 7. Cross-Modification Overlap Detection
- **Status**: Completed.
- **Context**: When modification #2's locator lived inside the region modification #1 replaced or deleted, the diagnostic was a bare "Snippet not found". The model that produced the patch then looked for a phantom change in the file instead of recognising its own overlapping instructions - the likeliest source of the "the data changed during application" reasoning seen in the wild.
- **Implementation**: Detection is post-hoc rather than preflight, which is both simpler and more precise: `consumed_log` records the text each `REPLACE`/`DELETE` removed, and a failing locator is looked up in it. The new `LOCATOR_CONSUMED` error names the modification that removed the locator, with a `FIX_HINTS` entry telling the model to fold the two edits together.

## 8. Post-Apply Structural Sanity Check
- **Status**: Completed (warning only).
- **Context**: A file whose brackets balanced before a patch and do not balance after it is almost always the result of a locator that cut a construct in half: the patch applies cleanly and the code does not compile.
- **Implementation**: `net_bracket_depth` (a `line_start_depths` run with clamping disabled, so stray closers stay visible) is compared before and after. A mismatch prints a warning naming the delta. Deliberately not an error, not even in strict mode: bracket counting is heuristic and plenty of legitimate text files are unbalanced by nature.
- **Next Steps**: Consider an opt-in `--check "gofmt -e {}"` hook for real syntax validation, which could then fail hard.

## 9. Version Numbering
- **Status**: Completed.
- **Context**: `ap.py` declared `AP_FORMAT_VERSION = "3.2"` while `ap.md` and `README.md` still described the format as 3.1, and `scope_end` is a genuine format addition that should not ship under a 3.1 label.
- **Implementation**: Spec and README retitled to 3.2, including every `AP 3.1` header in the examples. `AP_SUPPORTED_VERSIONS` already accepts 3.0/3.1/3.2, so existing patches keep applying.

## 10. Structural Awareness Is English-Brace-Centric
- **Status**: Open question.
- **Context**: `line_start_depths`, the nesting guard and `scope_end` share one crude tokenizer: `//`, `#` and `--` open line comments, `/* */` opens a block comment, and `'`, `"`, backtick open strings. Languages that disagree (Lisp `;`, SQL string escaping by doubling, Rust raw strings, JS regex literals, heredocs) will mis-count. The failure mode is benign - the guard does not fire, `scope_end` is ignored, the balance warning is skipped - but it is silent.
- **Next Steps**: Consider deriving the comment/string rules from the file extension, and skipping the structural features entirely for extensions that are not recognised as source code.

## 11. Fixture Comparison Is Positional, Not Declarative
- **Status**: Open question.
- **Context**: The older half of the suite maps a test name to an output path through a chain of `elif test_name == ...` branches in `run_tests.py`, and stores expectations as files in `expected/`. Adding a test means touching three places, which is exactly what `cases.py` was introduced to avoid. It also means a policy change like item 1 requires `--update-expected` rather than a readable diff.
- **Next Steps**: Migrate the file-based tests to `cases.py` incrementally; the declarative runner already supports everything most of them need.
