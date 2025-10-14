			        The 'ap' (AI-friendly Patch) Format
                                Version 1.0

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
       whitespace, blank lines) during the location phase, the format is
       resilient to code auto-formatting.

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
     this file conforms to. For this document, the value MUST be `"1.0"`.

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
   the following keys:

   - `action` (string, REQUIRED): The operation to perform. The value
     MUST be one of the following strings:
     - `REPLACE`: Replace the `Snippet` with the provided `content`.
     - `INSERT_AFTER`: Insert the `content` immediately after the `Snippet`.
     - `INSERT_BEFORE`: Insert the `content` immediately before the `Snippet`.
     - `DELETE`: Remove the `Snippet` from the file.
     - `CREATE_FILE`: Create a new file at `file_path` with the specified
       `content`.

   - `target` (mapping, CONDITIONALLY REQUIRED): A `Target` object that
     specifies where to apply the modification. This field MUST be
     present for all actions except `CREATE_FILE`.

   - `content` (string, CONDITIONALLY REQUIRED): The new code to be used
     for the operation. This field MUST be present for `REPLACE`,
     `INSERT_AFTER`, `INSERT_BEFORE`, and `CREATE_FILE`. It MUST be
     omitted for `DELETE`. The `content` SHOULD be provided without
     leading indentation. The Patcher is responsible for adding the
     correct indentation (see Section 3.2).

### 2.5. Target Object

   The `target` object is a mapping used to locate the code to be
   modified. It contains the following keys:

   - `snippet` (string, REQUIRED): A string of code (potentially
     multi-line) to be located within the file. This is the primary
     locator.
   - `anchor` (string, OPTIONAL): A string of code (potentially
     multi-line) to start search of `snippet` from. This is used
     to resolve ambiguity.
   - `include_leading_blank_lines` (integer, OPTIONAL): When specified, the
     Patcher's selection is expanded to include up to this number of
     consecutive blank lines immediately preceding the `snippet`.
   - `include_trailing_blank_lines` (integer, OPTIONAL): When specified, the
     Patcher's selection is expanded to include up to this number of
     consecutive blank lines immediately following the `snippet`.

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

   - **`DELETE`**: If the `target` `snippet` is not found, the operation is
     considered already complete and MUST be skipped.

   - **`REPLACE`**: If the content at the target location is already
     identical to the modification's `content`, the operation MUST be
     skipped.

   - **`INSERT_AFTER`**: If the code immediately following the `target`
     `snippet` already matches the `content`, the operation MUST be skipped.

   - **`INSERT_BEFORE`**: If the code immediately preceding the `target`
     `snippet` already matches the `content`, the operation MUST be skipped.

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

   **Important:** `anchor` and `snippet` must not start or end in the middle
   of a source code line (leading whitespace characters do not count).
   In other words, the first character of every anchor or snippet line
   must be the first non-whitespace character of corresponding source file
   line and the last character of every anchor or snippet line must be
   the last non-whitespace character of corresponding source file line.
   Special attention should be payed to comments located at the ends
   of lines. They are also considered part of the line, along with the
   whitespace separating them from the code.

   3.  **Scoping**: If an `anchor` is provided, the Patcher MUST first
       locate its unique occurrence using the normalized search strategy.
       The subsequent normalized search for the `snippet` MUST be performed
       only starting from that `anchor`. If the `anchor` is not found,
       the Patcher MUST report an error.

   4.  **Uniqueness and Precedence**:
       - **Anchor**: If an `anchor` is provided, the Patcher MUST find
         exactly one occurrence of it within the file. If zero or more
         than one occurrences are found, the Patcher MUST report an
         error.
       - **Snippet**:
         - If an `anchor` is provided, the Patcher's search for the
           `snippet` begins from the start of the located `anchor`.
           To be precise, the search scope for the snippet MUST begin
           at the first line of the located anchor and extend to the end
           of the file. The Patcher MUST use the *first* occurrence found
           within this scope. If zero occurrences are found, it MUST
           report an error.
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
     `include_trailing_blank_lines` are specified in the `target`, the
     Patcher MUST expand the region to be modified to include the
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

   A highly effective mental model for generating `ap` patches is to imagine
   giving instructions to a junior developer. The patch should be clear,
   unambiguous, and use the smallest possible context (`snippet` and `anchor`)
   to uniquely identify the code that needs changing. This approach naturally
   leads to robust, high-quality patches that are easy for both humans and
   machines to understand.

   To generate high-quality, seamless patches, an AI model MUST adhere
   to the following best practices when authoring an `.ap` file:

   - **Code Style Consistency**: Before generating `content`, the AI
     MUST analyze the target file to infer and match its existing
     code style. This includes, but is not limited to, conventions
     such as indentation (tabs vs. spaces), naming conventions (e.g.,
     `camelCase` vs. `snake_case`), brace style, maximum line length,
     and quoting style (single vs. double quotes). The generated code
     MUST be indistinguishable from the surrounding code.

   - **Comment Language and Style**: The AI MUST match the natural
     language of existing comments in the target file. For example,
     if most of comments are in German, new comments must also be
     in German. New code comments SHOULD only be added to clarify
     complex or non-obvious logic; self-explanatory code SHOULD NOT
     be commented.

   - **Separation of Explanations**: Explanations about *why* the patch
     is being made (the "intent" of the change) SHOULD be included as
     YAML comments within the `.ap` file itself. These meta-comments
     SHOULD NOT be inserted as code comments into the target file's
     `content`. The language of these explanatory YAML comments
     SHOULD match the language of the user's prompt.

   - **Minimalism and Focus**: Patches SHOULD be minimal and focused on
     the requested change. Refactoring unrelated code or making
     stylistic changes outside the scope of the task can lead to
     unexpected side effects and MUST be avoided unless explicitly
     requested.

   - **Locator Selection Strategy (`anchor`, `snippet`)**:
     To create robust and minimal patches, an AI model MUST follow a specific
     hierarchical strategy for selecting locators. The goal is to use the
     simplest possible method to uniquely and reliably identify the target code.
     The model MUST follow these steps in order:

     1.  **Identify Minimal `snippet`**: First, select the shortest possible
         `snippet` of code that is likely to be unique.

     2.  **Test for Uniqueness (File Scope)**: The AI MUST mentally check if
         this `snippet` is unique within the entire target file. If unique,
         the selection is complete. Use only the `snippet`. DO NOT add an
         `anchor` if it is not needed. If not unique, proceed to the next step.

     3.  **Define a Scoping `anchor`**: If the `snippet` is not unique,
         identify the smallest, most stable preceding semantic block of code
         (like a function/method signature) to serve as an `anchor`. The
         `anchor` MUST be unique within the file.

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
   version: "1.0"
   changes:
     - file_path: "src/calculator.py"
       modifications:
         - action: INSERT_AFTER
           target:
             snippet: "import math"
           content: "from typing import List"

         - action: REPLACE
           target:
             anchor: "def add(a, b):"
             snippet: "return a + b"
           content: |
             # New implementation supports summing a list
             if isinstance(a, List):
                 return sum(a)
             return a + b

         - action: DELETE
           target:
             snippet: |
               def get_pi():
                   return 3.14
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

