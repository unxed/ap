			        The 'ap' (AI-friendly Patch) Format
                                Version 1.0

## Abstract

   This document defines the 'ap' (AI-friendly Patch) format, a
   declarative, human-readable specification for describing changes to
   source code files. Traditional patch formats, based on line numbers
   and textual context (e.g., diff/patch), are brittle and poorly
   suited for generation by Large Language Models (LLMs). The 'ap'
   format addresses this by using semantic anchors and unique code
   snippets as locators, making it resilient to minor formatting changes
   and more aligned with the conceptual way AI models process code.

## Status of This Memo

   This memo provides information for the AI and developer communities. It
   does not specify an Internet standard of any kind. Distribution of
   this memo is unlimited.

## 1. Introduction

### 1.1. The Problem with Traditional Patches

   For decades, developers have used formats like `diff` and `patch` to
   represent and apply code changes. These formats are based on precise
   line numbers and surrounding context lines. While effective for
   version control systems that operate on byte-for-byte comparisons,
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
   - **Snippet**: A specific, multi-line string of code that the Patcher
     MUST locate within a file.
   - **Anchor**: An OPTIONAL, larger block of code that provides context
     to narrow the search scope for a `Snippet`.

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
     relative to the root of the project directory.

   - `modifications` (list, REQUIRED): A list of `Modification` objects
     to be applied sequentially to this file.

   - `newline` (string, OPTIONAL): Specifies the desired line ending
     format for the file. If provided, this value MUST be used. If
     omitted, the Patcher will attempt to detect the format from an
     existing file or fall back to the OS default for new files.
     Allowed values are `"LF"`, `"CRLF"`, and `"CR"`. This is
     particularly useful for the `CREATE_FILE` action.
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
     - `CREATE_FILE`: Create a new file at `file_path` with the specified `content`.

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

   - `snippet` (string, REQUIRED): A verbatim, potentially multi-line
     string of code to be located within the file. This is the primary
     locator.
- `anchor` (string, OPTIONAL): A larger, stable block of code (e.g., a
  full function or class definition) that contains the `snippet`. Its
  content MUST be a verbatim, character-for-character match of the code
  in the target file, including all whitespace and indentation. If
  provided, the Patcher MUST confine its search for the `snippet` to
  the scope of the `anchor`. This is used to resolve ambiguity.

## 3. Patcher Implementation Requirements
### 3.1. Search and Location Algorithm

   A Patcher utility MUST follow these rules when locating a `target`. The
   search strategies for `anchor` and `snippet` are intentionally different
   to provide both precision and flexibility.

   1.  **Anchor Search Strategy (Literal Match)**: An `anchor` MUST be
       located using a direct, literal, character-by-character search. This
       ensures the context is precisely and unambiguously identified. An AI
       generating a patch MUST ensure the `anchor` text is an exact copy
       from the source file, including all original whitespace and formatting.

   2.  **Snippet Search Strategy (Normalized Match)**: A `snippet` SHOULD be
       located using a "smart" or normalized search. The matching process MUST
       follow these steps:
       a. The `snippet` text is split into a list of lines.
       b. Any line containing only whitespace is removed from this list.
       c. Each remaining line has its leading and trailing whitespace removed.
       d. The Patcher then searches the target file for a sequence of non-empty
          lines that, after having their own leading/trailing whitespace
          removed, are identical to the processed list of snippet lines.
   This ensures that the match is based on the content of the lines, not
   their indentation or the blank lines between them, and it prevents
   ambiguous partial matches within a single line.

   3.  **Scoping**: If an `anchor` is provided, the Patcher MUST first
       locate its unique occurrence using the literal search strategy. The
       subsequent normalized search for the `snippet` MUST be performed
       only within the bounds of that `anchor`. If the `anchor` is not
       found, the Patcher MUST report an error.

   4.  **Uniqueness**: The Patcher MUST find exactly one occurrence of the
       `snippet` within its search scope (either the full file or the
       `anchor`'s scope). If zero or more than one occurrences are found,
       the Patcher MUST report an ambiguity error.
### 3.2. Modification Logic

   - **Indentation**: When performing any action involving `content`
     (`REPLACE`, `INSERT_AFTER`, `INSERT_BEFORE`), the Patcher SHOULD
     determine the indentation of the first line of the original `snippet`
     and apply that same indentation to every line of the new `content`.

   - **Sequential Application**: Modifications within a single
     `File Change` object MUST be applied sequentially in the order they
     are defined. The output of one modification becomes the input for
     the search phase of the next.

### 3.3. Error Handling

   The Patcher MUST provide clear, human-readable error messages for
   failure conditions, including but not limited to:
   - Target file not found.
   - Anchor or snippet not found.
   - Ambiguous anchor or snippet (multiple occurrences found).
   - Malformed patch file.

### 3.4. Post-processing

   After all modifications for a file have been applied, and before the
   file is written to disk, the Patcher MUST perform a final post-
   processing step:

   - **Trailing Whitespace Removal**: The Patcher MUST remove all trailing
     whitespace characters (spaces and tabs) from every line of the file's
     final content.

   This step ensures code cleanliness, as AI-generated code patches often
   include extraneous whitespace.

## 4. Complete Example

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

## 5. Security Considerations

   An `ap` patch file contains instructions to modify source code.
   Applying a patch from an untrusted source is equivalent to executing
   untrusted code. A malicious patch could alter security-critical files,
   introduce vulnerabilities (e.g., command injection, insecure
   dependencies), or modify build scripts to exfiltrate data. Patch
   files MUST be treated with the same level of scrutiny as any other
   executable code and should only be applied from trusted sources.

## 6. Rationale

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
     statement inside a function), the `anchor` is crucial for providing
     unambiguous context.

- **Best Practices for Anchor Generation**: To minimize the risk of formatting
  errors during AI generation, an `anchor` SHOULD be as short as possible
  while still being unique within the file. Often, the first line of a
  function signature or class definition is a much more robust anchor than
  the entire multi-line signature. This reduces the surface area for
  character-level mistakes that AI models can make when reproducing complex
  indentation.