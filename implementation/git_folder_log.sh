#!/usr/bin/env bash

# ====== CONFIGURATION ======
TARGET_PATH="$1"
START_POINT="$2"

OUT_DIR="repo_log"
DIFF_DIR="$OUT_DIR/diffs"
LOG_FILE="$OUT_DIR/commits.log"

# ====== FUNCTIONS ======
show_help() {
    echo "Usage: $0 <path> <start_point>"
    echo
    echo "Arguments:"
    echo "  <path>         File or directory to analyze (absolute or relative)."
    echo "  <start_point>  Starting point for the log. Can be a date or a commit hash."
    echo
    echo "Features:"
    echo "  - Auto-discovery: Detects the Git repository root from any file/folder path."
    echo "  - Auto-detection: Identifies if the start point is a YYYY-MM-DD date or a hash."
    echo "  - Hash support:   Works with both short and full commit hashes."
    echo "  - External:       Can be run from any directory."
    echo
    echo "Example:"
    echo "  $0 ~/projects/my-app/src 2024-01-01"
    echo "  $0 ./README.md a1b2c3d"
    exit 1
}

# ====== VALIDATION ======

if [[ -z "$TARGET_PATH" || -z "$START_POINT" ]]; then
    show_help
fi

if [[ ! -e "$TARGET_PATH" ]]; then
    echo "Error: Path '$TARGET_PATH' does not exist."
    exit 1
fi

# Get absolute path of the target
ABS_TARGET_PATH=$(realpath "$TARGET_PATH")

# Determine the Git Repository Root
# If target is a directory, check it directly. If it's a file, check its parent.
if [[ -d "$ABS_TARGET_PATH" ]]; then
    SEARCH_DIR="$ABS_TARGET_PATH"
else
    SEARCH_DIR=$(dirname "$ABS_TARGET_PATH")
fi

REPO_ROOT=$(git -C "$SEARCH_DIR" rev-parse --show-toplevel 2>/dev/null)

if [[ -z "$REPO_ROOT" ]]; then
    echo "Error: The path '$TARGET_PATH' is not inside a Git repository."
    exit 1
fi

echo "Repository found: $REPO_ROOT"

# ====== AUTO-DETECT MODE ======

# Check if START_POINT is a date (YYYY-MM-DD)
if [[ "$START_POINT" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    MODE_DESC="DATE ($START_POINT)"
    GIT_LOG_ARGS=("--since=$START_POINT")

# Check if START_POINT is a valid git commit/hash
elif git -C "$REPO_ROOT" rev-parse --quiet --verify "${START_POINT}^{commit}" > /dev/null 2>&1; then
    MODE_DESC="COMMIT HASH ($START_POINT)"
    GIT_LOG_ARGS=("${START_POINT}..HEAD")

else
    echo "Error: '$START_POINT' is neither a valid YYYY-MM-DD date nor a valid commit hash."
    exit 1
fi

echo "Detected mode: $MODE_DESC"

# ====== FETCH COMMITS ======

# We use absolute path to the file/folder to ensure git finds it regardless of REPO_ROOT
COMMITS=$(git -C "$REPO_ROOT" log "${GIT_LOG_ARGS[@]}" --pretty=format:%H -- "$ABS_TARGET_PATH")

if [[ -z "$COMMITS" ]]; then
    echo "No commits found for the given criteria."
    exit 0
fi

# ====== PROCESSING ======

# Prepare output directories (relative to where the script is executed)
mkdir -p "$DIFF_DIR"
> "$LOG_FILE"

echo "Processing commits..."
COUNT=0
# Use a while loop to handle the commit list properly
while read -r COMMIT; do
    if [[ -n "$COMMIT" ]]; then
        echo "$COMMIT" >> "$LOG_FILE"
        # Generate diff for the specific target within that commit
        git -C "$REPO_ROOT" show "$COMMIT" -- "$ABS_TARGET_PATH" > "$DIFF_DIR/$COMMIT.diff"
        ((COUNT++))
    fi
done <<< "$COMMITS"

echo "------------------------------------------"
echo "Success!"
echo "Target path:   $ABS_TARGET_PATH"
echo "Commits found: $COUNT"
echo "Log file:      $LOG_FILE"
echo "Diffs saved:   $DIFF_DIR/"