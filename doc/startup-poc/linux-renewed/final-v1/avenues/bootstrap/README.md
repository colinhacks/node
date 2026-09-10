# Rejected format-map bootstrap gate

## Disposition

Reject the proposed `get_format` gate. It is a no-op for the ordinary pinned build, not a Linux startup candidate. The proposed patch and its test were removed from this directory rather than leaving an invalid experiment for VM integration.

## Direct evidence

- `EnvironmentOptions::experimental_addon_modules` defaults to `true` in [`node_options.h:203-214`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/src/node_options.h#L203-L214). `EnvironmentOptions::strip_types` defaults to `HAVE_AMARO` in [`node_options.h:288-298`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/src/node_options.h#L288-L298). The preserved Linux builds use Amaro, so both conditions in the former gate are true by default.
- The option registrations bind `--experimental-addon-modules` and `--strip-types` to those fields ([`node_options.cc:631-634`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/src/node_options.cc#L631-L634), [`node_options.cc:1313-1318`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/src/node_options.cc#L1313-L1318)). The CLI documentation also records that type stripping is enabled by default ([`cli.md:2398-2415`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/doc/api/cli.md#L2398-L2415)).
- The locally built pinned Node artifact, `node/out/Release/node` (`v27.0.0-pre`), reports this directly with `--expose-internals`:

  ```text
  {"formatLoaded":true,"stripTypes":true,"addonModules":true}
  ```

  The command was:

  ```sh
  node/out/Release/node --expose-internals -p "const o=require('internal/options'); JSON.stringify({formatLoaded:process.moduleLoadList.includes('NativeModule internal/modules/esm/get_format'),stripTypes:o.getOptionValue('--strip-types'),addonModules:o.getOptionValue('--experimental-addon-modules')})"
  ```

  `--no-strip-types` changes only `stripTypes` to `false`; `addonModules` remains `true`, and `formatLoaded` remains `true`. This is a direct negative control against the intended mechanism.
- The Linux retained executables are x86-64 ELF binaries and cannot run on this arm64 macOS host. Their matching source/options configuration is the stronger applicability evidence; a Linux VM repetition would only reconfirm a no-op.

## Source path

`prepareExecution()` loads and initializes `internal/modules/esm/get_format` before module-loader initialization ([`pre_execution.js:171-179`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/lib/internal/process/pre_execution.js#L171-L179)). Its initializer adds the option-controlled extensions ([`get_format.js:15-34`](https://github.com/colinhacks/node/blob/f788616cf1515e30a8cce13513dbe8b30e567904/lib/internal/modules/esm/get_format.js#L15-L34)). Since both controlling options are default-on, guarding the load by either one does not remove it from default CJS, eval, or ESM startup.

## Prior work

The broader ESM-loader snapshot-preload removal remains separately rejected: it improved empty CJS 1.01085× but regressed empty ESM to 0.94321×. Blob/encoding preload removal similarly regressed empty ESM to 0.98125×. Those archived results are identified in [`../ARCHIVED-EVIDENCE.md`](../ARCHIVED-EVIDENCE.md). No renewed bootstrap mechanism is retained from this bounded check.

The earlier lazy built-in-record experiment remains unmeasured and is not promoted: it changes `BuiltinModule.map` value construction and ESM export-sync iteration, not merely an option-gated initialization path (the unmeasured branch is archived; it is not a pinned-source claim).
