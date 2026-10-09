# Issue Tracker: GitHub

Issues, specs, and tickets live in ArthurCapistrano/Lastro.
Use the `gh` CLI for tracker operations.

## Conventions

- Publish specs and implementation tickets as GitHub issues.
- Read an issue's full body and comments before working on it.
- Link tickets to their parent spec using GitHub sub-issues.
  If unavailable, put `Part of #<parent>` in the ticket body.
- Record blockers using native GitHub issue dependencies.
  If unavailable, use `Blocked by: #<number>` in the ticket body.
- A ticket is unblocked when all its blockers are closed.
- Apply the labels configured in [TRIAGE-LABELS.md](TRIAGE-LABELS.md).

## Pull Requests as a Triage Surface

PRs as a request surface: no.

## Wayfinding Operations

- Store the map as an issue labelled `wayfinder:map`.
- Link decision tickets as children of the map.
- Use `wayfinder:research`, `wayfinder:prototype`,
  `wayfinder:grilling`, or `wayfinder:task` on decision tickets.
- The frontier consists of open, unblocked, unassigned children.
- Claim a ticket by assigning it to the person driving the work.
- Resolve it with a resolution comment, close it, and add a named
  link and one-line summary to the map's Decisions so far.
