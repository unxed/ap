#!/bin/bash

# Check if the argument is provided
if [ -z "$1" ]; then
    echo "Error: Commit hash not specified."
    echo "Usage: $0 <commit_hash>"
    exit 1
fi

START_COMMIT=$1
OUTPUT_DIR="_diffs"

# Check if the specified commit exists in the repo
if ! git cat-file -t "$START_COMMIT" > /dev/null 2>&1; then
    echo "Error: Commit '$START_COMMIT' not found in the repository."
    exit 1
fi

# Create the output directory if it doesn't exist
if [ ! -d "$OUTPUT_DIR" ]; then
    mkdir "$OUTPUT_DIR"
    echo "Directory '$OUTPUT_DIR' created."
fi

# Get the list of commits:
# 1. The start commit itself
# 2. All commits after it up to HEAD
# We use --reverse to maintain chronological order (oldest to newest)
COMMITS_LIST="$START_COMMIT $(git rev-list --reverse ${START_COMMIT}..HEAD)"

echo "Starting diff extraction..."

for HASH in $COMMITS_LIST; do
    FILE_NAME="${OUTPUT_DIR}/${HASH}.diff"
    
    # 'git show' outputs the full commit info (metadata + diff).
    # If you need only the code changes without metadata (author, date, message), 
    # replace the line below with: git show --pretty="" -p "$HASH" > "$FILE_NAME"
    git show "$HASH" > "$FILE_NAME"
    
    echo "Saved: $FILE_NAME"
done

echo "Done! All files saved in '$OUTPUT_DIR'."
