# Domain Docs

This repository uses a single-context layout:

- `GLOSSARY.md` at the repository root.
- Architectural decision records in `docs/adr/`.

Use uppercase Markdown filenames, including ADRs such as
`0001-NAME-OF-DECISION.md`. Keep directory names lowercase.

Before exploring domain behavior, read the glossary and relevant ADRs
if they exist. If absent, proceed without requiring their creation.

Use glossary terms consistently in issues, interfaces, and tests.
Surface conflicts with existing ADRs before proposing changes.

Create documentation lazily through `/domain-modeling`:
the glossary when terms are resolved, and ADRs when significant
trade-offs warrant recording a decision.
