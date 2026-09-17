"""
Escrow provider: the OrderEscrow contract on an Ethereum JSON-RPC node.

Sits beside the Stripe adapter in the payments service (the same provider
pattern as notifications' EmailProvider). One OrderEscrow contract is deployed
per order; the customer signs exactly one transaction (pay), the shop's owner
key sends everything else and pays its gas. In development the node is Ganache
(``--wallet.deterministic``) and the owner key is topped up from Ganache's first
unlocked account at startup, the IEP "fund from the first of ten accounts" rule.

Payments stays stateless: the only escrow state is on chain and on the order
row in the orders service. Importing this module never touches the network --
only init_provider() / get_provider() connect, so the Stripe endpoints and
/readyz keep working when the chain is down.

web3.py 7.x names are used throughout (``raw_transaction``, ``is_connected``,
``chain_id``); the 6.x names from course material do not exist here.
"""
import json
import os
import pathlib
from decimal import Decimal, ROUND_HALF_UP
from typing import Callable, Optional

from eth_account import Account
from web3 import Web3
from web3.exceptions import ContractLogicError, Web3Exception

from logger import get_logger

logger = get_logger(__name__)

ESCROW_RPC_URL = os.getenv("ESCROW_RPC_URL", "http://ganache:8545")
ESCROW_PUBLIC_RPC_URL = os.getenv("ESCROW_PUBLIC_RPC_URL", "/rpc")       # what the browser uses
ESCROW_OWNER_PRIVATE_KEY = os.getenv("ESCROW_OWNER_PRIVATE_KEY")          # REQUIRED for a stable owner
WEI_PER_USD = int(os.getenv("WEI_PER_USD", "1000000000000000"))           # 0.001 ETH per dollar
ESCROW_COURIER_SHARE_BPS = int(os.getenv("ESCROW_COURIER_SHARE_BPS", "2000"))
ESCROW_OWNER_MIN_BALANCE_ETH = Decimal(os.getenv("ESCROW_OWNER_MIN_BALANCE_ETH", "10"))
ESCROW_OWNER_TOPUP_ETH = Decimal(os.getenv("ESCROW_OWNER_TOPUP_ETH", "100"))
ESCROW_EXPOSE_DEMO_ACCOUNTS = os.getenv("ESCROW_EXPOSE_DEMO_ACCOUNTS", "true").lower() == "true"
ESCROW_RPC_TIMEOUT = float(os.getenv("ESCROW_RPC_TIMEOUT", "5"))

# Ganache's --wallet.deterministic seed. The ten demo keys are DERIVED from it at
# runtime (eth_account HD wallet), never written down here.
GANACHE_MNEMONIC = "myth like bonus scare over problem client lizard pioneer submit female collect"
GANACHE_HD_PATH = "m/44'/60'/0'/0/{index}"

ARTIFACT_PATH = pathlib.Path(__file__).resolve().parent / "contracts" / "OrderEscrow.json"
STATE_NAMES = ["awaiting_payment", "funded", "in_delivery", "released", "cancelled"]   # index == Solidity enum
ZERO_ADDRESS = "0x" + "00" * 20
PAY_SELECTOR = "0x" + bytes(Web3.keccak(text="pay()"))[:4].hex()
REVERT_PREFIX = "execution reverted:"                                     # web3.py's ContractLogicError
GANACHE_REVERT_PREFIX = "VM Exception while processing transaction: revert"  # what Ganache puts after it


class EscrowUnavailable(Exception):
    """The chain is unreachable or no provider is configured (-> HTTP 503)."""


class EscrowNotFound(Exception):
    """No contract code at that address (-> HTTP 404)."""


class EscrowRevert(Exception):
    """A contract require() failed; ``reason`` is the bare revert string (-> HTTP 409)."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


# ============== pure helpers ==============

def load_artifact(path: pathlib.Path = ARTIFACT_PATH) -> dict:
    with open(path) as f:
        return json.load(f)


def usd_to_wei(amount_usd, wei_per_usd: int = WEI_PER_USD) -> int:
    """Fixed-rate conversion. Goes through Decimal(str(x)) so a float has no binary drift."""
    return int((Decimal(str(amount_usd)) * wei_per_usd).to_integral_value(rounding=ROUND_HALF_UP))


def revert_reason(exc: Exception) -> str:
    """The bare require() string out of a web3 ContractLogicError.

    web3 7 stores the text on ``.message``; ``str(exc)`` would render the whole
    ``(message, data)`` args tuple, so it is only the fallback. Geth-style nodes
    report ``execution reverted: <reason>``; Ganache v7 reports ``execution
    reverted: VM Exception while processing transaction: revert <reason>`` --
    both prefixes are stripped so the 409 detail (and orders' comparison
    against the locked strings) always sees the bare reason.
    """
    message = getattr(exc, "message", None)
    if not message:
        message = exc.args[0] if exc.args else str(exc)
    message = str(message).strip()
    for prefix in (REVERT_PREFIX, GANACHE_REVERT_PREFIX):
        if message.startswith(prefix):
            message = message[len(prefix):].strip()
    if len(message) >= 2 and message[0] == message[-1] and message[0] in "'\"":
        message = message[1:-1].strip()
    return message


def demo_accounts(count: int = 10) -> list[dict]:
    """Ganache's deterministic accounts, derived from the mnemonic with the HD wallet."""
    Account.enable_unaudited_hdwallet_features()
    accounts = []
    for i in range(count):
        acct = Account.from_mnemonic(GANACHE_MNEMONIC, account_path=GANACHE_HD_PATH.format(index=i))
        accounts.append({
            "index": i,
            "address": acct.address,
            "private_key": "0x" + bytes(acct.key).hex(),
        })
    return accounts


def state_name(enum_value: int) -> str:
    return STATE_NAMES[int(enum_value)]


def _hex(b) -> str:
    """0x-prefixed hex for a hash/bytes value (hexbytes' .hex() has no prefix)."""
    return "0x" + bytes(b).hex()


# ============== provider ==============

class EscrowProvider:
    """Deploys and drives OrderEscrow contracts from the shop's owner key."""

    def __init__(self, w3, owner_private_key: str, artifact: dict, *,
                 courier_share_bps: int = ESCROW_COURIER_SHARE_BPS, wei_per_usd: int = WEI_PER_USD):
        self.w3 = w3
        self.account = Account.from_key(owner_private_key)
        self.owner_address = self.account.address
        self.abi = artifact["abi"]
        self.bytecode = artifact["bytecode"]
        self.courier_share_bps = int(courier_share_bps)
        self.wei_per_usd = int(wei_per_usd)

    # --- node facts ---

    def is_connected(self) -> bool:
        try:
            return bool(self.w3.is_connected())
        except (OSError, TimeoutError, Web3Exception):
            return False

    def chain_id(self) -> int:
        return int(self.w3.eth.chain_id)

    def client_version(self) -> str:
        return str(self.w3.client_version)

    def is_ganache(self) -> bool:
        return "ganache" in self.client_version().lower()

    def owner_balance_wei(self) -> int:
        return int(self.w3.eth.get_balance(self.owner_address))

    def ensure_owner_funded(self, min_eth: Decimal = ESCROW_OWNER_MIN_BALANCE_ETH,
                            topup_eth: Decimal = ESCROW_OWNER_TOPUP_ETH) -> bool:
        """Top the owner up from the node's first unlocked account when it runs low.

        Only Ganache exposes unlocked accounts; on a public node ``eth.accounts``
        is empty and nothing happens (the guard against ever trying this for real).
        Returns True when a top-up transaction was sent.
        """
        accounts = list(self.w3.eth.accounts)
        if not accounts:
            return False
        balance = self.owner_balance_wei()
        if balance >= Web3.to_wei(min_eth, "ether"):
            return False
        tx_hash = self.w3.eth.send_transaction({
            "from": accounts[0],
            "to": self.owner_address,
            "value": Web3.to_wei(topup_eth, "ether"),
        })
        self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        logger.info("Escrow owner funded from the node's first account",
                    owner_address=self.owner_address, funder=accounts[0],
                    topup_eth=str(topup_eth), previous_balance_wei=str(balance))
        return True

    # --- contract operations ---

    def deploy(self, order_id: int, customer_address: str, amount_usd) -> dict:
        amount_wei = usd_to_wei(amount_usd, self.wei_per_usd)
        ctor = self.w3.eth.contract(abi=self.abi, bytecode=self.bytecode).constructor(
            Web3.to_checksum_address(customer_address), amount_wei, int(order_id), self.courier_share_bps,
        )
        receipt, tx_hash = self._send(ctor)
        return {
            "contract_address": receipt["contractAddress"],
            "deploy_tx_hash": tx_hash,
            "amount_wei": str(amount_wei),
        }

    def state(self, address: str) -> dict:
        s = self._status(address)
        courier = s[3]
        return {
            "state": state_name(s[0]),
            "owner": s[1],
            "customer": s[2],
            "courier": None if str(courier).lower() == ZERO_ADDRESS else courier,
            "price_wei": str(s[4]),
            "balance_wei": str(s[5]),
        }

    def invoice(self, address: str) -> dict:
        """The unsigned pay() transaction for the customer's wallet (ethers fills nonce/gas).

        ``value`` is a decimal string: JSON numbers cannot hold 10^18 safely.
        """
        s = self._status(address)
        return {
            "to": Web3.to_checksum_address(address),
            "value": str(s[4]),
            "data": PAY_SELECTOR,
            "chain_id": self.chain_id(),
        }

    def assign_courier(self, address: str, courier_address: str) -> dict:
        self._require_code(address)
        fn = self._contract(address).functions.assignCourier(Web3.to_checksum_address(courier_address))
        _, tx_hash = self._send(fn)
        return {"tx_hash": tx_hash, "state": self.state(address)["state"]}

    def release(self, address: str) -> dict:
        self._require_code(address)
        _, tx_hash = self._send(self._contract(address).functions.confirmDelivery())
        return {"tx_hash": tx_hash, "state": self.state(address)["state"]}

    def cancel(self, address: str) -> dict:
        self._require_code(address)
        _, tx_hash = self._send(self._contract(address).functions.cancel())
        return {"tx_hash": tx_hash, "state": self.state(address)["state"]}

    # --- internals ---

    def _contract(self, address: str):
        return self.w3.eth.contract(address=Web3.to_checksum_address(address), abi=self.abi)

    def _require_code(self, address: str) -> None:
        try:
            code = self.w3.eth.get_code(Web3.to_checksum_address(address))
        except (OSError, TimeoutError, Web3Exception) as e:
            raise EscrowUnavailable(str(e))
        if not code or bytes(code) in (b"", b"0x"):
            raise EscrowNotFound(address)

    def _status(self, address: str) -> tuple:
        self._require_code(address)
        try:
            return tuple(self._contract(address).functions.status().call())
        except ContractLogicError as e:
            raise EscrowRevert(revert_reason(e))
        except (OSError, TimeoutError, Web3Exception) as e:
            raise EscrowUnavailable(str(e))

    def _send(self, fn) -> tuple:
        """Build, sign with the owner key, send and wait. Returns (receipt, tx_hash_hex)."""
        try:
            tx = fn.build_transaction({
                "from": self.owner_address,
                "nonce": self.w3.eth.get_transaction_count(self.owner_address, "pending"),
                "chainId": self.chain_id(),
            })
            signed = self.w3.eth.account.sign_transaction(tx, self.account.key)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        except ContractLogicError as e:
            raise EscrowRevert(revert_reason(e))
        except (OSError, TimeoutError, Web3Exception) as e:
            raise EscrowUnavailable(str(e))
        if receipt["status"] != 1:
            raise EscrowRevert("Transaction reverted.")
        return receipt, _hex(tx_hash)


# ============== module-level factory ==============

_provider: Optional[EscrowProvider] = None
_w3_factory: Optional[Callable[[str], object]] = None


def _default_w3(url: str) -> Web3:
    return Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": ESCROW_RPC_TIMEOUT}))


def init_provider(w3_factory: Callable[[str], object] = _default_w3, *,
                  owner_key: Optional[str] = None, rpc_url: Optional[str] = None) -> Optional[EscrowProvider]:
    """Connect, fund the owner if needed, and install the module provider.

    Never raises: escrow is optional, so a missing key or an unreachable chain
    only logs a warning and leaves the provider unset (every /v1/escrow/* call
    then answers 503 while Stripe keeps working). The factory is remembered so
    get_provider() can retry with the same one.
    """
    global _provider, _w3_factory
    _w3_factory = w3_factory
    key = owner_key or ESCROW_OWNER_PRIVATE_KEY
    if not key:
        logger.warning("Escrow disabled: ESCROW_OWNER_PRIVATE_KEY is not set")
        _provider = None
        return None
    url = rpc_url or ESCROW_RPC_URL
    try:
        w3 = w3_factory(url)
        if not w3.is_connected():
            logger.warning("Escrow chain unreachable - Stripe keeps working", rpc_url=url)
            _provider = None
            return None
        p = EscrowProvider(w3, key, load_artifact())
        funded = p.ensure_owner_funded()
        logger.info("Escrow provider ready", owner_address=p.owner_address, chain_id=p.chain_id(),
                    client_version=p.client_version(), rpc_url=url, topped_up=funded)
    except (OSError, TimeoutError, ValueError, Web3Exception) as e:
        logger.warning("Escrow provider init failed", rpc_url=url, error=str(e))
        _provider = None
        return None
    _provider = p
    return p


def get_provider() -> EscrowProvider:
    """The live provider, re-initialised lazily.

    Ganache takes a few seconds to answer after ``docker compose up`` and
    payments may start first; the first escrow request after the node is up
    then succeeds without a restart, and the owner top-up runs at that moment.
    """
    if _provider is None or not _provider.is_connected():
        init_provider(_w3_factory or _default_w3)
    if _provider is None:
        raise EscrowUnavailable("escrow is not configured or the chain is unreachable")
    return _provider


def health() -> dict:
    p = _provider
    return {
        "enabled": p is not None,
        "rpc_url": ESCROW_RPC_URL,
        "owner_address": p.owner_address if p else None,
        "chain_id": p.chain_id() if p else None,
    }
