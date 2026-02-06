import os
import shutil
import re
from pathlib import Path

# This script scans the current directory to generate a lightweight replica of the C/C++ project structure
# in a folder named _cxx_structure, designed to provide architectural context to AI models without the overhead
# of implementation details. It employs a two-pass strategy where it first analyzes all source files to resolve
# and register files referenced via include directives, ensuring that template implementations or included C/C++
# files are captured. Subsequently, it recreates the folder hierarchy and populates it with all header files,
# CMake build configurations, and the explicitly included source files, effectively creating a compact
# interface-only version of the repository.

# ================= SETTINGS =================

# Directory where the structure will be copied
OUT_DIR = "_cxx_structure"

# Header file extensions (always copied)
HEADER_EXTS = {'.h', '.hpp', '.hxx', '.hh', '.inl', '.inc'}

# Extensions to scan for #include directives (to find included .cpp files)
SCAN_EXTS = HEADER_EXTS.union({'.c', '.cpp', '.cxx', '.cc', '.m', '.mm'})

# Build system files (always copied)
CMAKE_FILES = {'CMakeLists.txt'}
CMAKE_EXTS = {'.cmake'}

# Directories to ignore
IGNORE_DIRS = {'.git', '.vscode', '.idea', 'build', 'cmake-build-debug', '__pycache__', OUT_DIR}

# ================= LOGIC =================

def scan_includes(root_dir):
    """
    Pass 1: Scan all source files for #include "..." directives.
    Returns a set of absolute paths to files that are explicitly included.
    """
    included_files_absolute = set()
    
    # Regex to find local includes: #include "path/to/file"
    # We ignore <...> as those are typically system libraries.
    include_pattern = re.compile(r'^\s*#\s*include\s*"(.+?)"')

    print("--- Pass 1: Analyzing dependencies (includes) ---")
    
    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Filter out ignored directories
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        
        for filename in filenames:
            file_ext = os.path.splitext(filename)[1].lower()
            
            if file_ext in SCAN_EXTS:
                current_file_path = os.path.join(dirpath, filename)
                
                try:
                    with open(current_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        for line in f:
                            match = include_pattern.match(line)
                            if match:
                                include_path_raw = match.group(1)
                                
                                # Path resolution logic:
                                # 1. Try relative to the current file
                                resolved_path = os.path.join(dirpath, include_path_raw)
                                if os.path.isfile(resolved_path):
                                    included_files_absolute.add(os.path.abspath(resolved_path))
                                    continue
                                
                                # 2. Try relative to the project root
                                resolved_path_root = os.path.join(root_dir, include_path_raw)
                                if os.path.isfile(resolved_path_root):
                                    included_files_absolute.add(os.path.abspath(resolved_path_root))
                                    continue
                                
                except Exception as e:
                    print(f"Error reading {current_file_path}: {e}")

    print(f"Found {len(included_files_absolute)} files referenced via #include.")
    return included_files_absolute

def copy_structure(root_dir, out_dir, included_files_set):
    """
    Pass 2: Replicate the directory structure and copy relevant files.
    """
    print(f"--- Pass 2: Copying files to {out_dir} ---")
    
    if os.path.exists(out_dir):
        print(f"Cleaning up existing directory {out_dir}...")
        shutil.rmtree(out_dir)
    
    files_copied_count = 0

    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        
        for filename in filenames:
            src_file_path = os.path.join(dirpath, filename)
            abs_src_path = os.path.abspath(src_file_path)
            file_ext = os.path.splitext(filename)[1].lower()
            
            should_copy = False
            
            # Condition 1: It's a header file
            if file_ext in HEADER_EXTS:
                should_copy = True
            
            # Condition 2: It's a CMake file
            elif filename in CMAKE_FILES or file_ext in CMAKE_EXTS:
                should_copy = True
                
            # Condition 3: It's an source file found in Pass 1 (e.g., included .cpp or .tpp)
            elif abs_src_path in included_files_set:
                should_copy = True
                print(f"  -> Copying included source file: {filename}")

            if should_copy:
                # Calculate relative path to maintain folder structure
                rel_path = os.path.relpath(src_file_path, root_dir)
                dest_path = os.path.join(out_dir, rel_path)
                
                # Create destination subdirectories
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                
                shutil.copy2(src_file_path, dest_path)
                files_copied_count += 1

    print(f"Done. Total files copied: {files_copied_count}")

if __name__ == "__main__":
    current_working_dir = "."
    
    # 1. Collect all files that are explicitly included
    includes_found = scan_includes(current_working_dir)
    
    # 2. Copy headers, CMake files, and the found includes
    copy_structure(current_working_dir, OUT_DIR, includes_found)
