			        The 'ap' (AI-friendly Patch) Format
                                Version 2.0

## Abstract

   This document defines the 'ap' (AI-friendly Patch) format,
   a declarative, human-readable specification for describing changes
   to source code files.

   Traditional patch format, diff/patch, is too brittle for generation
   by Large Language Models (LLMs). The 'ap' format addresses this by
   using code fragments as locators, making it more aligned with the
   conceptual way AI models process code and also resilient to minor
   formatting changes.

## 1. Introduction

### 1.1. The Problem with Traditional Patches

   For decades, developers have used `diff`/`patch` format to represent
   and apply code changes. While effective for byte-for-byte comparisons,
   they are highly fragile when used in workflows involving AI code
   generation.

### 1.2. Core Principles of the 'ap' Format

   The 'ap' format is designed from the ground up to be robust and AI-
   friendly. It is built on three core principles:

   1.  **Semantic Locating**: Changes are located not by line numbers,
       but by referencing stable, semantic constructs like function
       signatures or unique blocks of code.

   2.  **Declarative Actions**: Instead of a list of added/removed
       lines, an `ap` patch contains explicit commands like `REPLACE`,
       `DELETE`, or `INSERT_AFTER`.

   3.  **Resilience**: By ignoring non-semantic differences (e.g.,
       leading and tailing whitespace, blank lines) during the location
       phase, the format is resilient to code auto-formatting.

### 1.3. Terminology

   The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT",
   "SHOULD", "SHOULD NOT", "RECOMMENDED", "MAY", and "OPTIONAL" in this
   document are to be interpreted as described in RFC 2119.

   - **Patch File**: A file containing a set of modifications, serialized
     in the `ap` format. The RECOMMENDED file extension is `.ap`.
   - **Patcher**: A tool or utility that parses a Patch File and applies
     the specified modifications to a target source code tree.
   - **Snippet**: A line or block of code that the Patcher MUST locate
     within a file. It SHOULD be unique within a file if no `anchor` is
     specified.
   - **Anchor**: An OPTIONAL line or block of code to narrow the search
     scope for a `Snippet`.

## 2. Format Specification

### 2.1. Serialization Format

   An `ap` patch file MUST be a valid YAML 1.2 document. YAML is chosen
   for its human-readability, support for comments, and excellent
   handling of multi-line strings.

### 2.2. Root Object

   The root of an `ap` document MUST be a mapping (object) containing the
   following keys:

   - `version` (string, REQUIRED): The version of the `ap` specification
     this file conforms to. For this document, the value MUST be `"2.0"`.

   - `changes` (list, REQUIRED): A list of `File Change` objects, where
     each object specifies modifications for a single file. The list MAY
     be empty.

### 2.3. File Change Object

   Each item in the `changes` list is a `File Change` object, which is a
   mapping containing the following keys:

   - `file_path` (string, REQUIRED): The path to the target file,
     relative to the `ap` patch file location. For security, this
     path MUST NOT contain components that traverse parent directories
     (e.g., `..`). This ensures the Patcher only operates within
     the specified directory.

   - `modifications` (list, REQUIRED): A list of `Modification` objects
     to be applied sequentially to this file.

   - `newline` (string, OPTIONAL): Specifies the desired line ending
     format for the file for the `CREATE_FILE` action. If provided,
     this value MUST be used. If omitted, the Patcher SHOULD fall back
     to the OS default for new files.
     Allowed values are `"LF"`, `"CRLF"`, and `"CR"`.

### 2.4. Modification Object

   Each item in the `modifications` list is a `Modification` object,
   which is a mapping that defines a single atomic change. It contains
   the following keys, all at the same level. A modification MUST use
   either the `snippet` key for point-based changes or the pair of
   `start_snippet` and `end_snippet` keys for range-based changes.
   They are mutually exclusive.

   - `action` (string, REQUIRED): The operation to perform. The value
     MUST be one of the following strings:
     - `REPLACE`: Replace the `snippet` or a range with the `content`.
     - `INSERT_AFTER`: Insert the `content` immediately after the `snippet`.
     - `INSERT_BEFORE`: Insert the `content` immediately before the `snippet`.
     - `DELETE`: Remove the `snippet` or a range from the file.
     - `CREATE_FILE`: Create a new file at `file_path` with the specified
       `content`.

   - `snippet` (string, CONDITIONALLY REQUIRED): A string of code to be
     located for a point-based change. This field MUST be present if
     `start_snippet` and `end_snippet` are not used. It MUST NOT be present
     if they are.

   - `start_snippet` (string, CONDITIONALLY REQUIRED): A string of code
     marking the beginning of a range to be modified. This field is used
     only for `REPLACE` and `DELETE` actions and MUST be paired with
     `end_snippet`.

   - `end_snippet` (string, CONDITIONALLY REQUIRED): A string of code
     marking the end of a range to be modified. The range is inclusive of
     both the start and end snippets. This field MUST be paired with
     `start_snippet`.

   - `content` (string, CONDITIONALLY REQUIRED): The new code to be used
     for the operation. This field MUST be present for `REPLACE`,
     `INSERT_AFTER`, `INSERT_BEFORE`, and `CREATE_FILE`. It MUST be
     omitted for `DELETE`. The `content` SHOULD be provided without
     leading indentation; the Patcher is responsible for adding it.

   - `anchor` (string, OPTIONAL): A string of code used to narrow the
     search scope for the `snippet`, resolving ambiguity.

   - `include_leading_blank_lines` (integer, OPTIONAL): Expands the
     selection to include up to this number of blank lines immediately
     preceding the `snippet`.

   - `include_trailing_blank_lines` (integer, OPTIONAL): Expands the
     selection to include up to this number of blank lines immediately
     following the `snippet`.

## 3. Patcher Implementation Requirements

### 3.0. Atomicity

   A Patcher MUST treat the application of an entire patch file as a
   single, atomic transaction. If any modification specified within the
   `changes` list cannot be successfully applied for any reason (e.g.,
   `snippet` not found, ambiguity, file not found for a non-`CREATE_FILE`
   action), the Patcher MUST abort the entire operation. It MUST NOT
   write any changes to any files on the filesystem. The target project
   directory MUST remain in its original state, as if the Patcher had
   never been run.

### 3.1. Idempotency

   A Patcher MUST apply modifications idempotently. Applying the same patch
   multiple times to the same source tree MUST NOT cause subsequent changes
   or errors after the first successful application. To achieve this, each
   modification within a change MUST be checked for its state before the
   operation is attempted, according to the following rules:

   - **`DELETE`**: If the `snippet` is not found, the operation is
     considered already complete and MUST be skipped.

   - **`REPLACE`**: If the content at the target location is already
     identical to the modification's `content`, the operation MUST be
     skipped.

   - **`INSERT_AFTER`**: If the code immediately following the `snippet`
     already matches the `content`, the operation MUST be skipped.

   - **`INSERT_BEFORE`**: If the code immediately preceding the `snippet`
     already matches the `content`, the operation MUST be skipped.

   - **`CREATE_FILE`**: If a file at `file_path` already exists and its
     content is identical to the provided `content`, the operation MUST
     be skipped. If the file exists with different content, the Patcher
     MUST report an error to prevent overwriting an unrelated file.

### 3.2. Search and Location Algorithm

   A Patcher utility MUST use a consistent, normalized search algorithm
   for locating both an `anchor` and a `snippet`. This approach provides
   resilience against non-semantic changes like indentation or spacing.
   The matching process MUST follow these steps:

   1.  The text to be found (`anchor` or `snippet`) is split into a list
       of lines.
   2.  Any line containing only whitespace is removed from this list.
   3.  Each remaining line has its leading and trailing whitespace removed.
   4.  The Patcher then searches the target file (or the relevant scope) for
       a sequence of non-empty lines that, after having their own
       leading/trailing whitespace removed, are identical to the processed
       list of lines from the text being sought.

   **Important:** `anchor` and `snippet` MUST NOT start or end in the middle
   of a source code line (leading whitespace characters do not count).
   In other words, the first character of every anchor or snippet line
   MUST be the first non-whitespace character of corresponding source file
   line and the last character of every anchor or snippet line must be
   the last non-whitespace character of corresponding source file line.
   By line here we mean a line in the source file, not a logical construct
   that can be broken across multiple lines, such as a function signature
   or a natural language sentence.
   Special attention should be payed to comments located at the ends
   of lines. They are also considered part of the line, along with the
   whitespace separating them from the code.

   3.  **Scoping**: If an `anchor` is provided, the Patcher MUST first
       locate its unique occurrence using the normalized search strategy.
       The subsequent normalized search for the `snippet` MUST be performed
       only starting from the line next to the last line of that `anchor`.
       If the `anchor` is not found, the Patcher MUST report an error.

   4.  **Uniqueness and Precedence**:
       - **Anchor**: If an `anchor` is provided, the Patcher MUST find
         exactly one occurrence of it within the file. If zero or more
         than one occurrences are found, the Patcher MUST report an
         error.
       - **Snippet**:
         - If an `anchor` is provided, the Patcher's search for the
           `snippet` begins at the line next to the last line of the
           located anchor and extend to the end of the file. The Patcher
           MUST use the *first* occurrence found within this scope.
           If zero occurrences are found, it MUST report an error.
           - **Range-based Search**: If `start_snippet` and `end_snippet`
             are provided (for `REPLACE` or `DELETE` actions):
             1. The Patcher first locates the `start_snippet` following the
                same uniqueness and scoping rules as a normal `snippet`
                (i.e., it must be unique within the file or within its `anchor`).
             2. After finding the `start_snippet`, the Patcher searches for the
                *first* occurrence of the `end_snippet` that appears *after* the
                end of the `start_snippet`.
             3. If the `start_snippet` is found but the `end_snippet` is not found
                in the remainder of the search scope, the Patcher MUST report an
                error. The entire region from the beginning of the `start_snippet`
                to the end of the `end_snippet` is considered the target for the
                modification.
         - If no `anchor` is provided, the Patcher MUST find exactly
           one occurrence of the `snippet` within the entire file. If
           zero or more than one occurrences are found, it MUST report
           an error.

### 3.3. Modification Logic

   - **Indentation**: When performing any action involving `content`
     (`REPLACE`, `INSERT_AFTER`, `INSERT_BEFORE`), the Patcher MUST
     determine the indentation of the first line of the original `snippet`
     and apply that same indentation to every line of the new `content`.

   - **Blank Line Inclusion**: If `include_leading_blank_lines` or
     `include_trailing_blank_lines` are specified in the modification object,
     the Patcher MUST expand the region to be modified to include the
     specified number of consecutive blank lines before or after the located
     `snippet`. This allows for controlled removal of surrounding whitespace,
     especially when using the `DELETE` action.

   - **Sequential Application**: Within a single `File Change` object,
     modifications MUST be processed sequentially in the order they are
     defined. The state of the file content *after* one modification
     has been calculated serves as the input for the search phase of the next
     modification. This sequential processing happens in memory before any
     files are written to disk, in accordance with the atomicity requirement
     (see Section 3.0).

   - **Insertion Context Awareness**:
     When generating `INSERT_AFTER` or `INSERT_BEFORE` actions to insert code
     inside a function, method, or block, an AI generating the patch MUST
     ensure that inserted content does **not** appear between a declaration
     or signature line and its opening brace or indentation block. Insertions
     intended to go *inside* a function or block MUST use a `snippet` that
     includes the opening `{` (in C-like languages) or the indented block start
     (in indentation-based languages such as Python) or a similar construct in
     other programming languages to guarantee syntactic correctness.

   - **Unique anchor**:
     During patch generation, the AI must ensure that the selected anchor
     appears only once in the source file, or choose a different anchor.

### 3.4. Error Handling

   The Patcher MUST provide clear, human-readable error messages for
   failure conditions, including but not limited to:
   - Target file not found.
   - Anchor or snippet not found.
   - Ambiguous anchor or snippet (multiple occurrences found).
   - Malformed patch file.

### 3.5. Post-processing

   After all modifications for a file have been applied, and before the
   file is written to disk, the Patcher MUST perform a final post-
   processing step:

   - **Trailing Whitespace Removal**: The Patcher MUST remove all trailing
     whitespace characters (spaces and tabs) from every line of the file's
     final content.

   This step ensures code cleanliness, as AI-generated code patches often
   include extraneous whitespace.

## 4. Best Practices for AI Generation

   To generate high-quality, seamless patches, an AI model MUST adhere
   to the following best practices when authoring an `.ap` file.

### 4.1. The "Plan-First" Principle

   A highly RECOMMENDED practice is to **decouple the problem-solving phase
   from the code-generation phase**. An AI SHOULD first generate a two-part
   plan in natural language. This plan SHOULD be included as a YAML comment
   at the very beginning of the patch file. It consists of a `Summary` and a
   `Plan`.

   - **Summary**: A high-level sentence explaining the "what" and "why" of the
     change, like a good commit message.
   - **Plan**: A numbered list of human-readable steps describing the "how"
     the change will be implemented.

   This structure allows the AI to first outline the overall goal, then break
   it down into concrete steps before generating the machine-readable code. It
   provides valuable context for human reviewers and serves as a clear guide
   for the AI itself.

### 4.2. Locator Selection Strategy

To create robust and minimal patches, an AI model MUST follow a specific
hierarchical strategy for selecting locators. The choice between a single
`snippet` and a `start_snippet`/`end_snippet` pair is the first and most
critical step.

1.  **Assess the Nature of the Change**: First, the AI must determine if the
    modification is a "point change" or a "range change".
    -   A **point change** involves a single line or a very short, atomic block
        (typically 1-2 lines). All `INSERT_AFTER` and `INSERT_BEFORE`
        actions are by definition point changes.
    -   A **range change** involves deleting or replacing a larger block of
        code (three or more lines), especially if the content is complex or
        contains empty lines, making it prone to transcription errors.

2.  **Choose the Locator Type Based on the Change**:
    -   For a **range change** (`REPLACE` or `DELETE`), the AI SHOULD use the
        `start_snippet`/`end_snippet` pair. This is the preferred method for
        multi-line blocks.
    -   For a **point change** (`REPLACE`, `DELETE`, `INSERT_AFTER`,
        `INSERT_BEFORE`), the AI MUST use a single `snippet`.

3.  **Select the Snippet(s) and Anchor (if needed)**: After choosing the
    locator type, the AI proceeds to select the content for the fields:
    -   **For a `snippet`**:
        1.  Identify the shortest possible `snippet` of code that is likely
            to be unique.
        2.  Test for Uniqueness (File Scope): The AI MUST mentally check if
            this `snippet` is unique within the entire target file.
        3.  If unique, the selection is complete. Use only the `snippet`. DO
            NOT add an `anchor` if it is not needed.
        4.  If not unique, identify the smallest, most stable preceding
            semantic block (like a function/method signature) to serve as
            an `anchor`. The `anchor` MUST be unique within the file.
    -   **For a `start_snippet`/`end_snippet` pair**:
        1.  Identify a `start_snippet` that is short, stable, and likely
            to be unique within its context.
        2.  Identify the first corresponding `end_snippet` that appears
            after the start snippet. This snippet should also be as short
            and stable as possible.
        3.  Test the `start_snippet` for uniqueness using the same logic as
            a single `snippet` (steps 2-4 above), adding an `anchor` if
            necessary to disambiguate it. The `end_snippet` does not need
            to be unique on its own; only its position relative to the
            `start_snippet` matters.

### 4.3. General Best Practices

   - **Structured Comment**: The patch file SHOULD begin with a commented-out
     `Summary` describing the overall goal, followed by a `Plan` with a
     numbered list of steps. The language SHOULD match the user's prompt.

   - **Universal Use of Literal Blocks**: For ALL `snippet`, `anchor`, and
     `content` fields (even single-line ones), the AI MUST use YAML's literal
     block scalar style (`|`). This enforces uniformity and completely avoids
     complex string escaping issues.

   - **Code Style Consistency**: Generated `content` MUST match the existing
     code style of the target file (indentation, naming conventions, brace
     style, quoting, etc.). The new code should be indistinguishable from
     the old.

   - **Comment Language and Style**: New code comments MUST match the
     natural language and style of existing comments in the target file.

   - **Minimalism and Focus**: Patches MUST be minimal and focused on the
     requested change. Unrelated refactoring MUST be avoided unless
     explicitly requested.

  - **Only full strings**: Before finalizing the output, the AI MUST
    perform a final self-check on the generated snippets and anchors.
    A common source of problems is using a substring of the original line
    of code instead of the entire line, from the frist non-space character
    to the last one. This shouldn't happen.

  - **YAML Indentation Integrity**: Before finalizing the output, the AI MUST
    perform a final self-check on the generated YAML's indentation. This is one
    of the most common and critical sources of errors. The check has three parts:

    1.  **Key Alignment**: All keys that are siblings in the same object (e.g.,
        `action`, `snippet`, `anchor`, and `content`) MUST have the exact same
        starting indentation.

    2.  **Multi-line Value Consistency**: When creating a multi-line value block
        with `|`, the YAML parser uses the indentation of the **first line** of
        the block to define the indentation for the entire block. Every subsequent
        line in that block MUST have at least that same level of indentation.
        Any line indented less than the first line will break the block and
        corrupt the file.

    3.  **List Item Alignment**: Each item in a YAML list (sequence) begins with a
        hyphen (`-`). All hyphens for items within the same list MUST have the exact
        same starting indentation. Incorrectly indenting a subsequent hyphen will
        cause the YAML parser to interpret it not as a new list item, but as a
        nested value of the preceding item, which is a common source of syntax
        errors when a block sequence is used as an implicit key.

    For example, this is a common, **invalid** generation showing violations
    of all three rules:

    ```yaml
    # WRONG:
    modifications:
      - action: REPLACE
        snippet: |
          def old_function():
              pass
          content: |       # Error 1 (Key Alignment): This key is misaligned with its sibling 'snippet'.
              def new_function():
            return True    # Error 2 (Multi-line Value): Indentation is less than the first line's, breaking the value block.
        - action: REPLACE  # Error 3 (List Item Alignment): This hyphen is misaligned, making it an invalid nested value, not a sibling list item.
          snippet: |
            // some code
    ```

    This is the **correct** structure:

    ```yaml
    # CORRECT:
    modifications:
      - action: REPLACE
        snippet: |
          def old_function():
              pass
        content: |         # Correctly aligned with 'snippet'.
          def new_function():
              return True  # Correctly indented, consistent with the block's first line.
      - action: REPLACE    # Correctly aligned, making it a sibling of the previous item.
        snippet: |
          // some code
    ```

## 5. Complete Example

   Given a target file `src/calculator.py`:

   ```python
   # A simple calculator module
   import math

   def add(a, b):
       # Deprecated: use sum() for lists
       return a + b

   def get_pi():
       return 3.14
   ```

   The following `patch.ap` file describes three modifications:

   ```yaml
   # Summary: Refactor the calculator module to enhance the `add` function
   # and remove deprecated code.
   #
   # Plan:
   #   1. Import the `List` type for type hinting.
   #   2. Update the `add` function to also handle summing a list of numbers.
   #   3. Remove the unused `get_pi` function.
   #
   version: "2.0"
   changes:
     - file_path: "src/calculator.py"
       modifications:
         - action: INSERT_AFTER
           snippet: |
             import math
           content: |
             from typing import List

         - action: REPLACE
           anchor: |
             def add(a, b):
           snippet: |
             return a + b
           content: |
             # New implementation supports summing a list
             if isinstance(a, List):
                 return sum(a)
             return a + b

         - action: DELETE
           snippet: |
             def get_pi():
                 return 3.14
           include_leading_blank_lines: 1
   ```

   After applying the patch, `src/calculator.py` MUST look like this:

   ```python
   # A simple calculator module
   import math
   from typing import List

   def add(a, b):
       # Deprecated: use sum() for lists
       # New implementation supports summing a list
       if isinstance(a, List):
           return sum(a)
       return a + b
   ```

## 6. Security Considerations

   An `ap` patch file contains instructions to modify source code.
   Applying a patch from an untrusted source is equivalent to executing
   untrusted code. A malicious patch could alter security-critical files,
   introduce vulnerabilities (e.g., command injection, insecure
   dependencies), or modify build scripts to exfiltrate data. Patch
   files MUST be treated with the same level of scrutiny as any other
   executable code and should only be applied from trusted sources.

## 7. Rationale

   - **YAML over JSON**: YAML was chosen for its superior readability,
     native support for multi-line strings (via `|` and `>`), and ability
     to include comments, which can be used to explain the intent behind
     a modification.

   - **Strictness on Ambiguity**: The requirement to fail on ambiguity
     (zero or multiple matches) is a deliberate design choice prioritizing
     safety and predictability over fallibility. It is better for a patch
     to fail cleanly than to be applied to the wrong location.

   - **Anchor and Snippet**: The two-level locating system (`anchor` and
     `snippet`) provides a balance between conciseness and robustness. For
     globally unique changes (like adding an import), a `snippet` is
     sufficient. For changes inside common structures (like a return
     statement inside a function), the `anchor` is crucial.

