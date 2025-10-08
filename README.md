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

## Getting Started

Let's say you have a file `greeter.py`:

```python
# greeter.py
def say_hello():
    # This is the line we want to change
    print("Hello, world!")
```

And you want the AI to change the greeting.

### Generating .ap file

You attach the .ap format spec (`ap.md` from this repository) to your prompt, and ask the AI ​​to give an answer in .ap format. So instead of generating the whole modified file, AI generates only small patch, lets call it `afix.ap` (this name is convenient in practice, as it places the file at the beginning of the list of files in the folder):

```yaml
# afix.ap
version: "1.0"
changes:
  - file_path: "greeter.py"
    modifications:
      - action: REPLACE
        target:
          snippet: 'print("Hello, world!")'
        content: 'print("Hello, AI-powered world!")'
```

### Applying the Patch

Use ap.py from the "implementation" folder of this repo to apply the patch:
```
python3 ap.py --patch afix.ap
```

### Checking the result

Your `greeter.py` file should be automatically updated:

```python
# greeter.py
def say_hello():
    # This is the line we want to change
    print("Hello, AI-powered world!")
```

## How It Works

The `ap` format is a simple YAML specification built on a few core ideas:

*   **Actions:** Each modification has a clear `action`, like `REPLACE`, `INSERT_AFTER`, `DELETE`, or `CREATE_FILE`.
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