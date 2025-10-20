# `ap`: The AI-friendly Patch Format

A robust, semantic patch format designed for code generation workflows.

![License](https://img.shields.io/badge/license-CC0_1.0-blue)

## Why does `ap` exist?

If you've ever used an AI to help you code, you're familiar with this cycle:

1.  **You:** "Change this function to handle a new edge case."
2.  **AI:** "Sure! Here is the updated code..." (provides a new code block)
3.  **You:** Manually copy the AI's code, find the right place in your file, paste it in, and fix the indentation.
4.  **You:** Run the code. It fails.
5.  **You:** Go back to the AI, explain the error, and repeat the whole cycle.

The manual copy-paste step is the biggest bottleneck in this process. It's slow, tedious, and error-prone.

**`ap` solves this problem.**

Instead of generating raw code, an AI can generate an `ap` patch file—a simple set of instructions for how to modify your code. You then use a command-line tool to apply these instructions automatically. No more manual copy-pasting.

Traditional patch formats (like `diff`) are not suitable for AIs because they rely on precise line numbers, which AIs struggle with. `ap` is designed from the ground up to be robust and AI-friendly, using semantic code snippets to locate changes instead of line numbers.

## What `ap` Is Not

To better understand the purpose of `ap`, it's equally important to understand what it is *not* designed to be.

*   **A general-purpose diff format.** `ap` is not a replacement for `diff` or `git diff`. It was designed not to describe the differences between two versions of a file, but to contain specific, semantically meaningful *instructions* for how to modify it.

*   **A diffing tool.** There are no plans for an `ap diff` utility that would create a patch by comparing two files. `ap` patches are designed to be *generated* by an AI, not *computed* by a diffing algorithm.

*   **A format for reversible patches.** There is no --revert option and none is planned: the format itselft does not contain enough information to implement it. When using it, all the work of version control and rollback of changes should be delegated to version control systems.

*   **A replacement for your favorite editor's AI plugin or console AI client.** On the contrary, `ap` can make these tools even more powerful.

*   **An efficient tool for modifying highly repetitive data.** The reliance on unique snippets makes `ap` poorly suited for tasks like modifying the 20th identical entry in a large array initialization. Since the `snippet` would match every entry, it would create an ambiguity error. You would likely need to replace the entire block, whereas a line-number-based tool or a simple script would be more effective.

*   **A version control system.** `ap` does not track history, manage branches, or resolve merge conflicts. It is a tool for applying a single, atomic set of changes to a codebase.

*   **A binary patch format.** `ap` is designed exclusively for text files, primarily source code. It is not suitable for modifying compiled files, images, or other binary data.

## Getting Started

Let's say you have a file `greeter.py`:

```python
def say_hello():
    # This is the line we want to change
    print("Hello, world!")
```

And you want the AI to change the greeting.

### Generating .ap file

You attach the .ap format spec (`ap.md` from this repository) to your prompt, and ask the AI ​​to give an answer in .ap format. So instead of generating the whole modified file, AI generates only small patch, lets call it `afix.ap` (this name is convenient in practice, as it places the file at the beginning of the list of files in the folder):

```
# Summary: Update the greeting message in greeter.py.
#
# Plan:
#   1. In `greeter.py`, replace the "Hello, world!" string with
#      "Hello, AI-powered world!".

f0cacc1a AP 3.0

f0cacc1a FILE
greeter.py

f0cacc1a REPLACE
f0cacc1a snippet
print("Hello, world!")
f0cacc1a content
print("Hello, AI-powered world!")
```

### Applying the Patch

Use a compatible patcher tool to apply the patch:
```
python3 ap.py afix.ap
```

### Checking the result

Your `greeter.py` file should be automatically updated:

```python
def say_hello():
    # This is the line we want to change
    print("Hello, AI-powered world!")
```

## How It Works

The `ap` format is a simple, line-oriented specification built on a few core ideas:

*   **Unique ID:** Each patch file starts with a unique 8-character hex ID (e.g., `f0cacc1a`). This ID is used as a prefix for every instruction line, making the format incredibly robust and eliminating a need for escaping and a potential confusion between instructions and the code itself.
*   **Directives:** All instructions are simple directives like `FILE`, `REPLACE`, `INSERT_AFTER`, `snippet`, or `content`. There's no complex syntax, indentation, or quoting to get wrong.
*   **Snippet:** The `snippet` is the exact piece of code you want to find. The patcher is smart enough to ignore leading whitespace and blank lines, making it resilient to formatting changes.
*   **Anchor (Optional):** To avoid ambiguity (e.g., when the same line of code appears in multiple functions), you can provide an `anchor` — a larger, unique block of code (like a function signature) to narrow down the search.

This approach makes the patch format robust, readable, and perfectly suited for generation by Large Language Models.

## Running the Test Suite

The project includes a full test suite to ensure the patcher works as expected. To run it:

```bash
python implementation/run_tests.py
```

## Contributing

Contributions are welcome! Whether it's improving the patcher, adding examples, or enhancing the documentation, feel free to open an issue or submit a pull request.

## License

This project is released into the public domain under the [CC0 1.0 Universal](LICENSE) license.
