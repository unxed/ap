#!/usr/bin/env python3
import os
import argparse

# Helper script to combine a whole folder of files into one text file
# for exposing to LLMs

def create_combined_file(source_dir, output_file):
    """
    Recursively finds all files in source_dir, concatenates them into
    output_file with a header for each file.
    """
    # Get absolute paths to safely compare and exclude the output file itself.
    abs_source_path = os.path.abspath(source_dir)
    abs_output_file = os.path.abspath(output_file)

    print(f"Source directory: {abs_source_path}")
    print(f"Output file:      {abs_output_file}")

    if not os.path.isdir(abs_source_path):
        print(f"Error: Source directory '{source_dir}' not found.")
        return

    try:
        with open(abs_output_file, 'w', encoding='utf-8') as outfile:
            for root, dirs, files in os.walk(abs_source_path):
                # Sort files and directories to ensure a consistent order
                files.sort()
                dirs.sort()

                for filename in files:
                    file_path = os.path.join(root, filename)

                    if os.path.abspath(file_path) == abs_output_file:
                        continue
                    # Basic ignore patterns to avoid including VCS, pycache, etc.
                    if ".git" in file_path or "__pycache__" in file_path or file_path.endswith(".pyc"):
                        continue

                    # Use relative path for a cleaner header
                    relative_path = os.path.relpath(file_path, abs_source_path)
                    print(f"  -> Adding {relative_path}")

                    outfile.write(f"=== BEGIN {relative_path} ===\n")

                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as infile:
                            content = infile.read()
                            outfile.write(content)

                        # Add a newline only if the file doesn't already end with one.
                        if content and not content.endswith('\n'):
                            outfile.write('\n')

                    except Exception as e:
                        outfile.write(f"[Error reading file (likely binary): {e}]\n")

                    # Add an extra newline for better separation between files.
                    outfile.write("\n")

    except IOError as e:
        print(f"Error: Could not write to output file '{output_file}': {e}")
        return

    print("\nDone. All files have been combined.")

def main():
    """
    Parses command-line arguments and runs the main function.
    """
    parser = argparse.ArgumentParser(
        description="Combine all files in a directory and its subdirectories into a single text file.",
        formatter_class=argparse.RawTextHelpFormatter # For better help text formatting
    )

    parser.add_argument(
        'source',
        nargs='?',
        default='src',
        help="The source directory to scan.\n(default: 'src')"
    )

    parser.add_argument(
        'output',
        nargs='?',
        default='allfiles.txt',
        help="The name of the output file.\n(default: 'allfiles.txt')"
    )

    args = parser.parse_args()

    create_combined_file(args.source, args.output)


if __name__ == "__main__":
    main()
