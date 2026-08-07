# Outstanding Design Questions & Deferred Tasks

This file documents deferred improvements, potential bugs, and architectural concerns
for the `ap` patcher and specification.

## 1. Trailing Newlines in Rewritten Files
- **Status**: Deferred.
- **Context**: The patcher currently does not guarantee a trailing newline at the end of rewritten files. Forcing this would break 48 test fixtures since they expect exact physical outputs.
- **Next Steps**: Now that the `--update-expected` flag has been added to `run_tests.py`, we can enable the trailing newline policy in `ap.py` and run `python implementation/run_tests.py --update-expected` to safely regenerate all affected expectations in a single step.

## 2. Hybrid Search Suffix-Matching for Single-line Locators
- **Status**: Deferred.
- **Context**: The hybrid search algorithm (`smart_find` in `ap.py`) matches the first line of a multi-line locator as a suffix to accommodate minor prefix variations. However, when the locator is only one line long, this suffix-match logic still applies, which can cause the patcher to mistakenly match substrings of much longer lines.
- **Next Steps**: Restrict the suffix-matching heuristic to multi-line locators only, ensuring that single-line snippets require exact line matching. This change must be coordinated with the expectation of test `24_heuristics` and the core spec.

## 3. Redundant Project Directory Prefix in File Paths
- **Status**: Completed.
- **Context**: LLM code generators sometimes prefix file paths with the project/repository directory name (e.g. `my_project/src/file.py`), depending on whether they assume the patch will be applied from inside or outside the project folder.
- **Implementation**: Added a dual heuristic in `ap.py` to automatically detect and strip redundant prefixes.
  1. For existing files, it strips any prefix that leads to a valid file path on disk.
  2. For newly created files/folders, it checks if a subdirectory inside the remaining path exists while the leading prefix does not (e.g. `src` exists, but `my_project` does not).
  3. If none of the above matches, it checks if the prefix has a starts/endswith relationship with the parent project folder name (length >= 2).