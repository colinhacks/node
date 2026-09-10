# Fork CI results

The [exact-source run](https://github.com/colinhacks/node/actions/runs/34423776381) completed at candidate `f788616cf1515e30a8cce13513dbe8b30e567904`. All six Linux/macOS jobs passed; both Windows jobs failed the same four JavaScript tests, so the run is **not green**.

| Platform | Pristine baseline | Candidate |
| --- | --- | --- |
| Linux x64 | Passed | Passed |
| Linux arm64 | Passed | Passed |
| macOS arm64 | Passed | Passed |
| Windows x64 | Native passed; four JavaScript failures | Native passed; same four JavaScript failures |

The baseline is `8af75451e9041cd6058080ad3d4a65546797b418`. Each matrix pair builds its own source on the same hosted-runner class with the same declared toolchain and command selection. Hosted CI is a compatibility check, not a controlled performance comparison.

## Windows failures

Both baseline and candidate failed:

- `parallel/test-child-process-exec-any-shells-windows`
- `parallel/test-dlopen-binary`
- `parallel/test-permission-dlopen-binary`
- `parallel/test-vfs-addon`

The shell test invokes every discovered shell. The inaccessible WindowsApps alias was narrowly excluded from both jobs; a remaining shell returns `4294967295`, but the logs do not identify which executable or its cause. Prepending Git Bash would not fix a test that invokes all discovery results.

The three loading failures report Windows sharing violations. Their root cause is unassigned; source ordering and delete-on-close behavior are hypotheses, not a demonstrated cause. No existing test was removed, skipped or weakened to obtain a pass.

The candidate's earlier private-V8 ICU-header build failure was fixed. This run builds the private cases and passes all 238 cctest cases; the pristine baseline passes 226. Both Windows native TAP plans contain 249 entries, including 11 skips and one TODO, with zero unexpected failures.

## Scope

The [fork workflow](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/.github/workflows/fork-startup-ci.yml) uses Node's `make test-ci` on Linux/macOS and `vcbuild` native/JavaScript CI selections on Windows. It retains the failure verdict and uploads logs even when tests fail.

- These are release-mode hosted runs, not the full upstream fleet.
- Debug, sanitizers, every architecture, configured-FIPS distributions and the addon ecosystem are not comprehensively covered.
- The Linux PGO/ThinLTO performance artifacts have separate [native VM gates](LINUX-RENEWED.md). Fork Actions does not validate those exact compiler/profile binaries.
- Subsequent documentation-only commits preserve this source, test and workflow tree. They do not turn this failed run into a green run or claim new exact-head CI coverage.

No upstream PR, merge or release is represented by these results.

## Retained evidence

The [parsed eight-job summary](CI-SUMMARY.json) records native/JavaScript counts, artifact provenance and job links. The [archive inventory](CI-EVIDENCE-SHA256SUMS.txt) hashes the retained local raw responses, logs, downloaded artifact ZIPs and reports. Full raw CI evidence remains preserved locally; it is not duplicated in this documentation directory.

While the GitHub artifacts remain available, download the eight job bundles with:

```sh
gh run download 34423776381 --repo colinhacks/node --dir ci-34423776381
gh run view 34423776381 --repo colinhacks/node --log > ci-34423776381.log
```
