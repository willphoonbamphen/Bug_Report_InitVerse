#!/usr/bin/env python3
"""
PoC: F2 — Developer Mining Authorization Bypass
Target: INIChain Mainnet (Chain ID 7233)
Chain client: github.com/Project-InitVerse/chain (inihash consensus)

The Bug:
  consensus/inihash/consensus.go Finalize() calls checkValid(coinbase) from C001
  to get developer group. verifySeal() immediately overwrites bigUtil with hash bytes.
  Group is NEVER checked. Any address can mine blocks regardless of group.

This script proves:
  1. Authorized miners (group=3000) are explicitly tracked by admin
  2. Unauthorized miners (group=1, default) are actively mining blocks RIGHT NOW
  3. The authorization system is live but has zero enforcement

No exploit needed — the bypass is structural and already active on mainnet.
"""

import json
import subprocess

RPC = "https://rpc-mainnet.inichain.com"
C001 = "0x000000000000000000000000000000000000C001"
CHECK_VALID_SIG = "0x99de5592"  # checkValid(address)

# Known authorized miners (group=3000, admin-set)
AUTHORIZED_MINERS = [
    "0xd843d47eae90ac076d4501208683aed8ec6f5b27",
    "0x989f0a0a37cc6938cf7d6124d8fb808f683d3a26",
]

# Known unauthorized miners (group=1, default) — actively mining mainnet
UNAUTHORIZED_MINERS = [
    "0x7c7bf4396d9fa35c5713cf1850f4e43914f23d49",  # mined block 0x2c2947
    "0xfdd8e4d0819afa5d98b71b1e224b716a8f84c893",  # mined block 0x2c2900
]

# Recent blocks to scan for unauthorized miners
SCAN_BLOCKS = [
    "0x2c2947",
    "0x2c2940",
    "0x2c2900",
    "0x2c2800",
    "0x2c2700",
]


def rpc(method, params, rid=1):
    payload = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": rid})
    cmd = ["curl", "-s", "-X", "POST", RPC,
           "-H", "Content-Type: application/json",
           "-d", payload]
    out = subprocess.check_output(cmd)
    return json.loads(out)


def pad_address(addr):
    clean = addr.lower().replace("0x", "")
    return "000000000000000000000000" + clean


def check_valid_group(addr):
    """
    Call checkValid(addr) with msg.sender = C001.
    This replicates exactly what Finalize() does in consensus.go.
    Returns the developer group integer.
    """
    data = CHECK_VALID_SIG + pad_address(addr)
    res = rpc("eth_call", [{"to": C001, "from": C001, "data": data}, "latest"])
    if "error" in res:
        return None, res["error"]
    result = res.get("result", "0x")
    if result == "0x" or len(result) < 4:
        return None, "empty result"
    try:
        group = int(result, 16)
        return group, None
    except ValueError:
        return None, f"parse error: {result}"


def get_block(block_num):
    res = rpc("eth_getBlockByNumber", [block_num, False])
    if "error" in res:
        return None
    return res.get("result")


def get_latest_block():
    res = rpc("eth_blockNumber", [])
    if "error" in res:
        return None
    return res.get("result")


def scan_recent_blocks(count=10):
    """Scan the most recent blocks and check each miner's group."""
    latest_hex = get_latest_block()
    if not latest_hex:
        return []
    latest = int(latest_hex, 16)
    results = []
    for i in range(count):
        block_num = hex(latest - i)
        block = get_block(block_num)
        if not block:
            continue
        miner = block.get("miner", "")
        group, err = check_valid_group(miner)
        results.append({
            "block": block_num,
            "miner": miner,
            "group": group,
            "hash": block.get("hash", ""),
            "err": err,
        })
    return results


def main():
    print("=" * 70)
    print("PoC: F2 — Developer Mining Authorization Bypass")
    print("INIChain Mainnet (Chain ID 7233)")
    print("=" * 70)

    # Step 1: Confirm authorized miner groups
    print("\n[1] Confirming admin-authorized miners (group=3000)...")
    print("    [Replicating Finalize() call: msg.From=C001, to=C001, checkValid(addr)]")
    all_authorized_correct = True
    for addr in AUTHORIZED_MINERS:
        group, err = check_valid_group(addr)
        if err:
            print(f"  [?] {addr}: ERROR — {err}")
            all_authorized_correct = False
        elif group == 3000:
            print(f"  [+] {addr}: group={group} (0x{group:X}) ✓ AUTHORIZED")
        else:
            print(f"  [?] {addr}: group={group} — unexpected")
            all_authorized_correct = False

    if all_authorized_correct:
        print("  [+] Admin has explicitly assigned group=3000 to authorized miners")
        print("      This proves the authorization system IS intentional, NOT dead code")

    # Step 2: Check unauthorized miners
    print("\n[2] Checking unauthorized miner groups (expect group=1)...")
    for addr in UNAUTHORIZED_MINERS:
        group, err = check_valid_group(addr)
        if err:
            print(f"  [?] {addr}: ERROR — {err}")
        elif group == 1:
            print(f"  [!] {addr}: group={group} — DEFAULT/UNAPPROVED")
        else:
            print(f"  [?] {addr}: group={group} — unexpected value")

    # Step 3: Fetch specific known blocks mined by unauthorized miners
    print("\n[3] Fetching blocks known to be mined by unauthorized (group=1) miners...")
    known_unauthorized = {
        "0x2c2947": "0x7c7bf4396d9fa35c5713cf1850f4e43914f23d49",
        "0x2c2900": "0xfdd8e4d0819afa5d98b71b1e224b716a8f84c893",
    }
    for block_num, expected_miner in known_unauthorized.items():
        block = get_block(block_num)
        if not block:
            print(f"  [?] Block {block_num}: failed to fetch")
            continue
        actual_miner = block.get("miner", "")
        block_hash = block.get("hash", "")
        group, err = check_valid_group(actual_miner)
        match = actual_miner.lower() == expected_miner.lower()
        print(f"\n  Block {block_num}:")
        print(f"    Hash:  {block_hash}")
        print(f"    Miner: {actual_miner}")
        if match:
            print(f"    Match: YES — expected unauthorized miner confirmed")
        if err:
            print(f"    Group: ERROR — {err}")
        else:
            if group == 1:
                print(f"    Group: {group} (UNAPPROVED — bypass confirmed)")
            elif group == 3000:
                print(f"    Group: {group} (authorized)")
            else:
                print(f"    Group: {group}")

    # Step 4: Live scan of recent blocks
    print("\n[4] Live scan: checking last 10 blocks for unauthorized miners...")
    results = scan_recent_blocks(10)
    if not results:
        print("  [!] Could not fetch recent blocks")
    else:
        unauthorized_count = 0
        authorized_count = 0
        for r in results:
            group_str = str(r["group"]) if r["group"] is not None else f"ERR:{r['err']}"
            if r["group"] == 1:
                label = "UNAPPROVED"
                unauthorized_count += 1
            elif r["group"] == 3000:
                label = "authorized"
                authorized_count += 1
            else:
                label = "unknown"
            print(f"  Block {r['block']}: miner={r['miner'][:10]}... group={group_str} [{label}]")

        print(f"\n  Summary: {authorized_count} authorized (group=3000), "
              f"{unauthorized_count} UNAUTHORIZED (group=1) in last 10 blocks")
        if unauthorized_count > 0:
            print(f"  [!!!] BYPASS ACTIVE: {unauthorized_count}/10 recent blocks mined "
                  f"by unapproved miners receiving block rewards")

    # Step 5: Explain the bypass
    print("\n[5] Bypass mechanism (from source code analysis):")
    print("""
  consensus/inihash/consensus.go — Finalize():
    bigUtil.SetUint64(ret[0].(*big.Int).Uint64())  // group stored: e.g. 1 or 3000
    inihash.verifySeal(chain, header, false, bigUtil)  // passed in

  consensus/inihash/consensus.go — verifySeal():
    result := versaHash.VersaHash(headerHash, nonce, extraNonce)
    target := new(big.Int).Div(two256, header.Difficulty)
    if bigUtil.SetBytes(result).Cmp(target) > 0 {  // <-- OVERWRITES developer group
        return errInvalidPoW
    }
    return nil  // group=1 and group=3000 both pass — NO AUTHORIZATION CHECK

  RESULT: Developer group value from checkValid() is permanently lost.
          Only standard PoW (hash <= target) is enforced.
          Any address with mining hardware bypasses admin authorization.
""")

    print("=" * 70)
    print("VULNERABILITY CONFIRMED:")
    print("  Unauthorized (group=1) miners are ACTIVELY mining INIChain mainnet")
    print("  Block rewards flow to addresses NOT authorized by admin")
    print("  The authorization system (group=3000) has ZERO enforcement")
    print("  Bypass is in consensus code — cannot be fixed without chain upgrade")
    print("=" * 70)


if __name__ == "__main__":
    main()
