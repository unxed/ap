#!/usr/bin/env bash
set -euo pipefail

OWNER="unxed"
REPO="f4"

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <issue-number>" >&2
    exit 1
fi

ISSUE="$1"
API="https://api.github.com/repos/$OWNER/$REPO/issues/$ISSUE"

OUTFILE="${OWNER}_${REPO}_issue_${ISSUE}.json"

echo "Fetching issue #${ISSUE}..."

issue=$(
    curl -fsSL \
        -H "Accept: application/vnd.github+json" \
        "$API"
)

comments_url=$(jq -r '.comments_url' <<<"$issue")

comments=$(
    curl -fsSL \
        -H "Accept: application/vnd.github+json" \
        "$comments_url"
)

jq -n \
    --argjson issue "$issue" \
    --argjson comments "$comments" '
{
  issue: {
    id: $issue.id,
    number: $issue.number,
    url: $issue.html_url,
    title: $issue.title,
    state: $issue.state,
    author: $issue.user.login,
    created_at: $issue.created_at,
    updated_at: $issue.updated_at,
    closed_at: $issue.closed_at,
    labels: ($issue.labels | map(.name)),
    assignees: ($issue.assignees | map(.login)),
    milestone: ($issue.milestone.title // null),
    reactions: $issue.reactions.total_count,
    body: $issue.body
  },

  discussion: (
    [
      {
        type: "issue",
        id: $issue.id,
        url: $issue.html_url,
        author: $issue.user.login,
        created_at: $issue.created_at,
        updated_at: $issue.updated_at,
        reactions: $issue.reactions.total_count,
        body: $issue.body
      }
    ]
    +
    (
      $comments
      | sort_by(.created_at)
      | map({
          type: "comment",
          id: .id,
          url: .html_url,
          author: .user.login,
          created_at: .created_at,
          updated_at: .updated_at,
          reactions: .reactions.total_count,
          body: .body
      })
    )
  )
}
' >"$OUTFILE"

echo "Saved to $OUTFILE"