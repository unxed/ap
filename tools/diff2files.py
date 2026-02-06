import os
import shutil
import re
import sys

# This script looks at specified .diff file, identifies the changed file paths,
# creates a corresponding directory structure within a dedicated output folder
# named _out, and copies the actual files from the local environment
# while preserving their original folder hierarchy.

def copy_changed_files(diff_file, output_folder="_out"):
    """
    Parses a diff file and copies modified files into a specific folder
    while maintaining the directory structure.
    """
    # Regex to find the destination file path in the diff (lines starting with +++ b/)
    file_pattern = re.compile(r'^\+\+\+ b/(.*)')

    if not os.path.isfile(diff_file):
        print(f"Error: File '{diff_file}' not found.")
        return

    # Create or refresh the output directory
    if os.path.exists(output_folder):
        print(f"Cleaning existing output folder: {output_folder}")
        shutil.rmtree(output_folder)
    os.makedirs(output_folder)

    files_to_copy = []

    try:
        # Step 1: Parse the diff file to get the list of files
        with open(diff_file, 'r', encoding='utf-8') as f:
            for line in f:
                match = file_pattern.match(line)
                if match:
                    file_path = match.group(1).strip()
                    # Skip /dev/null (indicates a deleted file)
                    if file_path != "/dev/null":
                        files_to_copy.append(file_path)

        if not files_to_copy:
            print("No modified files found in the diff.")
            return

        print(f"Found {len(files_to_copy)} files in diff. Starting copy...")

        # Step 2: Copy files maintaining structure
        copied_count = 0
        for file_path in files_to_copy:
            if os.path.exists(file_path):
                # Define destination path
                destination_path = os.path.join(output_folder, file_path)
                destination_dir = os.path.dirname(destination_path)

                # Create necessary subdirectories
                os.makedirs(destination_dir, exist_ok=True)

                # Copy file with metadata (timestamps, etc.)
                shutil.copy2(file_path, destination_path)
                print(f"  [OK] {file_path}")
                copied_count += 1
            else:
                print(f"  [SKIP] {file_path} (File not found on disk)")

        print(f"\nSuccess! {copied_count} files copied to '{output_folder}'.")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    # Check if the filename argument is provided
    if len(sys.argv) < 2:
        print("Usage: python extract_diff.py <path_to_diff_file>")
        print("Example: python extract_diff.py changes.diff")
        sys.exit(1)

    # Get the filename from the first command line argument
    input_diff = sys.argv[1]
    copy_changed_files(input_diff)
