# Phase 6C — Preregistration v1.3 (editorial) freeze

**Status: COMPLETE** (documentation only; no code, sim, or main-run).

Date: 2026-10-06.

## Four-edit diff (vs `3e2ac05`)

```diff
-**Authors:** Ronith Sharmila (corresponding). Research design and analysis plan drafted with an AI research assistant (Claude); implementation by an AI coding assistant (Cursor). Disclosed in the paper.
-**Date:** 2026-10-06 (v1.2; supersedes v1.1, frozen at 3c654d4) · **Registry:** OSF · **Repository:** https://github.com/heyronith/constituition (frozen commit hash recorded at submission) · **Target venue:** TMLR
+**Authors:** Ronith Sharmila (corresponding).
+**Date:** 2026-10-06 (v1.3; supersedes v1.2, frozen at 3e2ac05) · **Registry:** OSF · **Repository:** https://github.com/heyronith/constituition (frozen commit hash recorded at submission)

-… plus 20 lead-written hard items …
+… plus 20 experimenter-written hard items …

- The lead analyst is a Claude model; Claude models were excluded as judges.
```

`git diff 3e2ac05 -- docs/PREREGISTRATION.md` shows only these four edits.

## Grep results

Pattern: `claude|cursor|AI research assistant|AI coding assistant|venue|TMLR|lead` (case-insensitive).

| Source | Matches |
|---|---|
| `docs/PREREGISTRATION.md` | **none** |
| `docs/PREREGISTRATION.pdf` (extracted text) | **none** |

§2.4 “an assistant deployed by Ashgrove Insurance” retained.

## SHA-256

| File | v1.2 (`3e2ac05`) | v1.3 |
|---|---|---|
| `docs/PREREGISTRATION.md` | `af7ec96baa1c233c4a6944d9a1203df64d67f25b9e9d01fe33b483cc0a8ffa6a` | `847fa5504b98b4d434706b6f70ee505bd22f2084bd80f7a233b64bb05af23bcc` |
| `docs/PREREGISTRATION.pdf` | `8a3131564fb1c80f37bd436d905564d00c5e41f887b0e2c5806fdc94c6a365f1` | `4dc2f5841ad3d322255dce27cd772677027126a1233b7cdceee8baa332b6caf4` |

## Code hashes

All eleven analysis-code / companion hashes recomputed and **identical** to v1.2 (`3e2ac05`). Design and analysis unchanged.

## Freeze

- Freeze commit: `be75115`
- D54 logged in `docs/DECISIONS.md`
- Pushed to `main`
