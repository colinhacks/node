# Independent source-package audit

## Verdict

**Pass after correction.** The initial audit found a malformed `series` file;
the generator and emitted file were corrected, and a read-side recheck confirms
an exact 22-line manifest-ordered series. Patch digests remain unchanged. The
initial failure is retained in the evidence below.

This audit used only temporary `GIT_INDEX_FILE` indexes under `/tmp`; it did not
apply patches to a worktree, build Node, run a VM, change Git refs, or make any
runtime or performance conclusion.

## Findings

1. **Resolved — generated `series` previously could not be replayed as a
   line-delimited series.**
   `xxd -g 1 source-package-v1/series` shows `5c 6e` after the first filename,
   rather than byte `0a`; `read_text().splitlines()` consequently yields one
   filename containing all 22 names. The direct cause is
   [`build-source-package-v1.py`](../build-source-package-v1.py#L261), whose
   f-string uses `\\n`, producing a literal backslash and `n` in Python. It
   was changed to `"\n".join(names) + "\n"`, with an assertion that a
   line-read reproduces `names`. The corrected file contains 22 byte-`0a`
   delimiters and exactly the manifest's 22 filenames in order; all 22 patch
   SHA-256 values still match the manifest. See
   [`post-fix-evidence.json`](post-fix-evidence.json). The original failure is
   preserved in [`evidence-before-series-fix.json`](evidence-before-series-fix.json).

2. **Pass — frozen provenance.** All 18 package patches are byte-identical to
   `startup-lab/public-platform-pr/patches`, and each original and packaged
   SHA-256 equals its frozen manifest entry. All 22 package patch digests also
   equal their renewed manifest entries.

3. **Pass — complete index-only replay and source identity.** Applying the
   manifest sequence from `8af75451e9041cd6058080ad3d4a65546797b418` produced
   `9526a6758f0d6a11b779afc556a7eb0a86da84f9`; the first 18 produced
   `3166f9876aa2586b4008f7c722ba406e8258d44a`. Every recorded `from_tree` and
   `to_tree` transition matches the independently calculated index tree. All
   64 paths changed by the package have a blob identical to public-worktree
   HEAD `f788616cf1515e30a8cce13513dbe8b30e567904`; the only 324 remaining
   tree differences are 323 `doc/` paths and one `.github/` path. The renewed
   four patches touch the expected 13 source/test/build paths and no `doc/` or
   `.github/` paths.

4. **Pass — prerequisite claims, with README wording correction.** Exhaustive
   subsets of every frozen patch that overlaps each candidate patch's paths,
   expanded by their frozen dependency closure and applied from upstream base,
   found these unique minimum frozen contexts: `19: [1]`,
   `20: [1,2,9,14,15]`, `21: [1,2,9,14,15]`, and `22: []`. Separately applying
   after frozen patch 18 has unique minima `19: []`, `20: []`, `21: [20]`, and
   `22: []`. Thus patch 21's **complete upstream-base prerequisite closure**
   is `[1,2,9,14,15,20]`; the initial README "Minimal base closure" cell only
   shows the frozen part and relies on a separate, differently scoped
   "Additional closure after patch 18" cell. That presentation is ambiguous
   and does not state the exact complete base closure requested by the package
   contract. The corrected README now states `[1,2,9,14,15,20]` in patch 21's
   base-closure cell while retaining `patch 20` in the separately scoped
   after-frozen-18 cell. The read-side recheck confirms that exact wording.

## Evidence and commands

The reproducible independent checker is [`verify.py`](verify.py); its captured
result is [`evidence.json`](evidence.json). Supplementary digest and path-scope
facts are captured in [`supplemental-evidence.json`](supplemental-evidence.json).
The checker does not import or invoke the generator. Its successful checks were
`constants`, `frozen_bytes`, `full_replay`, `frozen_replay`, `transitions`,
`source_mapping`, and `dependency_closures`; its intentionally failing `series`
check records the initial delimiter defect before correction.

```sh
python3 startup-lab/platform/linux-renewed/source-package-audit-v1/verify.py
xxd -g 1 startup-lab/platform/linux-renewed/source-package-v1/series
git -C worktrees/public-startup diff --name-only \
  9526a6758f0d6a11b779afc556a7eb0a86da84f9 \
  f788616cf1515e30a8cce13513dbe8b30e567904
```

The checker deliberately continues replay from manifest patch filenames after
recording the malformed `series`; that isolates the artifact-format failure
from validation of the patch payload itself.
