#!/usr/bin/env python3
"""Write the declared native startup and official throughput configurations."""
import argparse
import hashlib
import json
from pathlib import Path

THROUGHPUT = {
    "buffer-from": ("buffers/buffer-from.js", ["source=array", "len=2048", "n=800000"]),
    "buffer-compare": ("buffers/buffer-compare.js", ["size=4096", "n=1000000"]),
    "transcode": ("buffers/buffer-transcode.js", ["fromEncoding=latin1", "toEncoding=utf8", "length=1000", "n=100000"]),
    "crypto-hash": ("crypto/create-hash.js", ["n=100000"]),
    "crypto-random": ("crypto/randomBytes.js", ["size=64", "n=100000"]),
    "crypto-bulk-hash": ("crypto/hash-stream-throughput.js", ["n=500", "algo=sha256", "type=buf", "len=1048576", "api=legacy"]),
    "stream-pipe": ("streams/pipe.js", ["n=5000000"]),
    "url-parse": ("url/whatwg-url-parse.js", ["withBase=false", "type=short", "e=12"]),
    "decode-windows1252": ("util/text-decoder.js", ["encoding=windows-1252", "ignoreBOM=0", "fatal=0", "type=Buffer", "content=one-byte-string", "len=16384", "n=10000"]),
    "fs-read": ("fs/readFileSync.js", ["encoding=utf8", "path=existing", "hasFileDescriptor=false", "n=10000"]),
    "fs-stat": ("fs/bench-statSync.js", ["n=100000", "statSyncType=statSync"]),
    "module-cached": ("module/module-loader.js", ["name=/index.js", "dir=abs", "files=100", "n=1000", "cache=true"]),
    "module-uncached": ("module/module-loader.js", ["name=/index.js", "dir=abs", "files=100", "n=100", "cache=false"]),
    "http-parser": ("http/bench-parser.js", ["len=16", "n=100000"]),
}

STARTUP = {
    "empty-eval": ("", ""),
    "hello": ("console.log('hello')", "hello\n"),
    "builtins": ("const a=require('node:assert/strict');const p=require('node:path');const u=require('node:url');a.equal(p.basename(u.fileURLToPath(u.pathToFileURL(p.resolve('x.js')))),'x.js')", ""),
    "first-sha256": ("require('node:assert/strict').equal(require('node:crypto').createHash('sha256').update('abc').digest('hex'),'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')", ""),
    "first-random": ("require('node:assert/strict').equal(require('node:crypto').randomBytes(32).length,32)", ""),
    "first-windows1252": ("require('node:assert/strict').equal(new TextDecoder('windows-1252').decode(Uint8Array.of(128)),String.fromCodePoint(8364))", ""),
    "worker": ("const {Worker}=require('node:worker_threads');const w=new Worker('require(\"node:worker_threads\").parentPort.postMessage(42)',{eval:true});w.once('message',v=>{require('node:assert/strict').equal(v,42);w.terminate()})", ""),
    "http-ready": ("const s=require('node:http').createServer();s.listen(0,'127.0.0.1',()=>{require('node:assert/strict').ok(s.address().port>0);s.close()})", ""),
    "first-intl": ("require('node:assert/strict').equal(new Intl.DateTimeFormat('en-US',{timeZone:'UTC',year:'numeric'}).format(0),'1970')", ""),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifact", action="append", required=True, help="label=absolute-path")
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    artifacts = {label: str(Path(path).resolve()) for label, path in
                 (item.split("=", 1) for item in args.artifact)}
    if len(artifacts) < 2:
        raise ValueError("At least two named artifacts required")
    workloads = []
    for suffix in ("cjs", "mjs"):
        fixture = output / ("empty." + suffix)
        fixture.write_bytes(b"")
        workloads.append(dict(name="empty-" + suffix, argv=[str(fixture)],
                              cwd=str(source), expected_stdout=""))
    workloads.extend(dict(name=name, argv=["-e", program], cwd=str(source),
                          expected_stdout=stdout) for name, (program, stdout) in STARTUP.items())
    workloads.append(dict(name="help", argv=["--help"], cwd=str(source)))
    startup = dict(schema=1, artifacts=artifacts, workloads=workloads,
                   seed=20260908, warmups=10, rounds=350, timeout_seconds=60)
    (output / "startup.json").write_text(json.dumps(startup, indent=2) + "\n")
    throughput = []
    files = [source / "benchmark" / p for p in ("run.js", "common.js", "_cli.js")]
    for name, (relative, settings) in THROUGHPUT.items():
        category, filename = relative.split("/", 1)
        argv = [str(source / "benchmark/run.js"), "--format", "csv", "--filter", filename]
        for setting in settings:
            argv.extend(["--set", setting])
        argv.append(category)
        throughput.append(dict(name=name, argv=argv, cwd=str(source),
                               metric=dict(kind="node-csv-throughput", expected_filename=str(Path(relative)))))
        files.append(source / "benchmark" / relative)
    plan = dict(schema=1, artifacts=artifacts, workloads=throughput,
                seed=20260909, warmups=3, rounds=20, timeout_seconds=180)
    (output / "throughput.json").write_text(json.dumps(plan, indent=2) + "\n")
    hashes = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    (output / "benchmark-sources.json").write_text(json.dumps(hashes, indent=2) + "\n")
    baseline = artifacts[sorted(artifacts)[0]]
    control = dict(startup, artifacts={"same-a": baseline, "same-b": baseline},
                   workloads=workloads[:3], rounds=100)
    (output / "identity-control.json").write_text(json.dumps(control, indent=2) + "\n")


if __name__ == "__main__":
    main()
