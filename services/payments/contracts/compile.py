#!/usr/bin/env python3
"""Turn solc combined-json (stdin) into the committed OrderEscrow.json artifact.

Usage:
    solc --combined-json abi,bin --optimize OrderEscrow.sol | compile.py <OrderEscrow.sol> <OrderEscrow.json>

Invoked by `make contract-compile`, which runs solc in the ethereum/solc:0.8.28
docker image (solc-bin has no macOS-arm64 binary). Stdlib only, so it runs on
any python3. The output is sorted and pretty-printed so a recompile of the same
source is byte-identical; `source_sha256` lets the unit tests catch a .sol edit
that was not followed by a recompile.
"""
import hashlib
import json
import sys

CONTRACT_NAME = "OrderEscrow"


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(f"usage: {argv[0]} <{CONTRACT_NAME}.sol> <{CONTRACT_NAME}.json>  (solc combined-json on stdin)", file=sys.stderr)
        return 1
    sol_path, out_path = argv[1], argv[2]

    raw = sys.stdin.read()
    if not raw.strip():
        print("compile.py: no solc output on stdin", file=sys.stderr)
        return 1
    data = json.loads(raw)

    key = next((k for k in data.get("contracts", {}) if k.endswith(f":{CONTRACT_NAME}")), None)
    if key is None:
        print(f"compile.py: no contract named {CONTRACT_NAME} in solc output (keys: {sorted(data.get('contracts', {}))})", file=sys.stderr)
        return 1
    contract = data["contracts"][key]

    # solc 0.8.28 emits the ABI as a JSON array; older releases emitted a JSON string.
    abi = contract["abi"] if isinstance(contract["abi"], list) else json.loads(contract["abi"])
    bytecode = "0x" + contract["bin"]
    # "0.8.28+commit.7893614a.Linux.g++" -> "0.8.28+commit.7893614a"
    solc_version = data["version"].split(".Linux")[0].split(".Darwin")[0]
    with open(sol_path, "rb") as f:
        source_sha256 = hashlib.sha256(f.read()).hexdigest()

    artifact = {
        "contract": CONTRACT_NAME,
        "solc_version": solc_version,
        "source_sha256": source_sha256,
        "abi": abi,
        "bytecode": bytecode,
    }
    with open(out_path, "w") as f:
        json.dump(artifact, f, indent=2, sort_keys=True)
        f.write("\n")

    size = len(json.dumps(artifact, indent=2, sort_keys=True)) + 1
    print(f"wrote {out_path} ({size} bytes, {len(abi)} ABI entries)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
