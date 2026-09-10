# Public evidence bytes

Public evidence replaces local home-directory prefixes with `/REDACTED_HOME`. Numerical samples, command options and executable digests are unchanged. Private originals remain in the retained archives.

- The [sanitization ledger](SANITIZATION.json) records original and public SHA-256 values for transformed files, including compressed and decoded bytes.
- The [payload manifest](manifest.json) hashes every current public file except itself. Its verifier rejects missing, altered or unlisted payloads.
- Hashes embedded in original reports refer to the original evidence bytes. Use the ledger to distinguish these from public redacted bytes; do not compare an original-report digest directly with a redacted file.
- The [artifact manifest](ARTIFACTS.json) identifies the actual measured executables and profiles. Path redaction does not change those identities.

The raw records retain every measured value and failure verdict. Redaction is not sample filtering.
