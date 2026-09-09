# Source commits

The 18 source commits reproduce the [patch manifest](patches/manifest.json) exactly. Documentation and fork CI are separate commits. Dependencies in the patch digest still apply; arbitrary subsets have not all been runtime-tested.

Each source commit carries the human author’s DCO sign-off and an assistance disclosure. DCO sign-off is not a cryptographic signature.

| Patch | Commit | Change |
| --- | --- | --- |
| 01 | [b4484f53e8](https://github.com/colinhacks/node/commit/b4484f53e8c2ae88f0c29937831557252ac95048) | build: support Darwin ThinLTO and profile-guided optimization |
| 02 | [73b500ad72](https://github.com/colinhacks/node/commit/73b500ad723f88452dbbc0b0274195494d88c950) | build: hide private symbols in static Darwin executables |
| 03 | [df4cc13d86](https://github.com/colinhacks/node/commit/df4cc13d8691a61a3febafa68f197d359831dca9) | deps: use native 128-bit arithmetic for rapidhash secrets |
| 04 | [49c872782e](https://github.com/colinhacks/node/commit/49c872782e82298a2ea12d4e82ae2221c439bd1c) | src: borrow static option help text |
| 05 | [00e7a307ee](https://github.com/colinhacks/node/commit/00e7a307ee1a84bab21aa41d7d5aa36a0515bf04) | src: set Abseil deadlock policy before V8 initialization |
| 06 | [0c98923007](https://github.com/colinhacks/node/commit/0c9892300724a4ba664b09af661842902651a972) | deps: dispatch fixed-size V8 snapshot copies directly |
| 07 | [97ef69ba47](https://github.com/colinhacks/node/commit/97ef69ba47b71f7656ffb753c27c12e1f356fc2a) | deps: load CoreFoundation lazily in CCTZ |
| 08 | [7ba2ed193a](https://github.com/colinhacks/node/commit/7ba2ed193af8c7986538898534a665e5197a2bd9) | crypto: load Darwin certificate frameworks on demand |
| 09 | [24ae797976](https://github.com/colinhacks/node/commit/24ae7979764986f3dcf89d06255c70d93b68e390) | build: hide private bundled ICU symbols on Darwin |
| 10 | [7e4f9e9a0f](https://github.com/colinhacks/node/commit/7e4f9e9a0f84de540e10d310a19e60c558d4b6dc) | lib: compact single-byte encoding tables |
| 11 | [809f94db49](https://github.com/colinhacks/node/commit/809f94db491967f21836c31dc33bd97741541d47) | crypto: register OpenSSL cleanup with its Darwin image |
| 12 | [abcdf9a2c6](https://github.com/colinhacks/node/commit/abcdf9a2c69f542d3e09400c479c91853251b0c5) | deps: screen small factors in rapidhash secret generation |
| 13 | [62eb574422](https://github.com/colinhacks/node/commit/62eb574422808e4d6546ee3aeef81c5e9012fa6c) | deps: use Montgomery arithmetic for rapidhash primality tests |
| 14 | [12ab979323](https://github.com/colinhacks/node/commit/12ab979323eb328e4687c5af1c5ce423489cf0ea) | build: support trained Darwin linker order files |
| 15 | [7d02bda129](https://github.com/colinhacks/node/commit/7d02bda129b903c5a205d30492355b7a864d25c2) | build: bound whole-program virtual call optimization |
| 16 | [a63cbf1e81](https://github.com/colinhacks/node/commit/a63cbf1e816792eb9c1103b9c4be0290f8459453) | src: use OS entropy for V8 startup seeds |
| 17 | [9fdeca2ae0](https://github.com/colinhacks/node/commit/9fdeca2ae07b39432d096d7d6df8cd21bf595b47) | build: isolate Windows LTO flags from external addons |
| 18 | [9b4c6bc82b](https://github.com/colinhacks/node/commit/9b4c6bc82b0a11aef7cd46422f0e604086d9ed6a) | build: support optional Linux Clang ThinLTO |

The pinned base is `8af75451e9041cd6058080ad3d4a65546797b418` and the source-only tree is `3166f9876aa2586b4008f7c722ba406e8258d44a`.

## Renewed Linux commits

The [renewed Linux report](LINUX-RENEWED.md) describes commits 19–22 and their current validation status. The frozen 18-patch replay manifest above is unchanged.
