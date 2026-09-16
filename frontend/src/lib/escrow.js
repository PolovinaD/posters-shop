/**
 * Escrow helpers (ESC-05).
 *
 * The private key never leaves the browser: it is turned into an ethers Wallet
 * here, used to sign exactly ONE transaction (the `pay()` invoice that orders
 * hands back from POST /orders/{id}/escrow), and discarded. No browser wallet
 * extension is involved (locked decision 2) — a pasted key or a Ganache demo
 * account is all the customer needs.
 *
 * Pure functions first so `node` can test them without a DOM; `payInvoice` is
 * the only function that touches the network.
 */
import { JsonRpcProvider, Wallet, formatEther } from 'ethers';

const KEY_HEX = /^[0-9a-fA-F]{64}$/;

/**
 * Accept a key with or without the `0x` prefix and surrounding whitespace;
 * always return the `0x`-prefixed form. Runs before ethers sees the key so a
 * typo surfaces as our message, not ethers' INVALID_ARGUMENT.
 */
export function normalizePrivateKey(raw) {
  const v = String(raw ?? '').trim();
  const hex = v.startsWith('0x') || v.startsWith('0X') ? v.slice(2) : v;
  if (!KEY_HEX.test(hex)) throw new Error('Enter a 64-character hex private key');
  return `0x${hex}`;
}

/** The customer types no address: it is derived from the key (locked decision 2). */
export function addressFromKey(raw) {
  return new Wallet(normalizePrivateKey(raw)).address;
}

/** `wei` is a decimal string from the API (JSON cannot hold 10^18 safely). */
export function formatEth(wei) {
  return formatEther(BigInt(wei));
}

/**
 * Mirrors payments' usd_to_wei: cents first, then BigInt, so 19.99 USD at
 * 10**15 wei/USD is exactly 19990000000000000 with no float drift.
 */
export function usdToWei(usd, weiPerUsd) {
  const cents = BigInt(Math.round(Number(usd) * 100));
  return ((cents * BigInt(weiPerUsd)) / 100n).toString();
}

/** Mirrors OrderEscrow.confirmDelivery: courier gets price * bps / 10000, owner the rest. */
export function payoutSplit(amountWei, courierShareBps) {
  const total = BigInt(amountWei);
  const courierWei = (total * BigInt(courierShareBps)) / 10000n;
  return { ownerWei: (total - courierWei).toString(), courierWei: courierWei.toString() };
}

/**
 * '/rpc' -> 'http://host/rpc' (the nginx / vite proxy to Ganache); absolute
 * URLs pass through. The trailing-slash strip is defensive only — `new URL`
 * already yields `.../rpc` for a path input.
 */
export function resolveRpcUrl(
  rpcUrl,
  origin = typeof window !== 'undefined' ? window.location.origin : 'http://localhost',
) {
  return new URL(rpcUrl, origin).toString().replace(/\/$/, '');
}

/**
 * Sign and send the unsigned invoice `{to, value, data, chain_id}` from orders.
 * ethers fills nonce, gas and fee fields itself; `staticNetwork` skips the
 * eth_chainId round-trip because the chain id is already known.
 */
export async function payInvoice({ rpcUrl, privateKey, invoice }) {
  const chainId = Number(invoice.chain_id);
  const provider = new JsonRpcProvider(resolveRpcUrl(rpcUrl), chainId, { staticNetwork: true });
  const wallet = new Wallet(normalizePrivateKey(privateKey), provider);
  const tx = await wallet.sendTransaction({
    to: invoice.to,
    value: BigInt(invoice.value),
    data: invoice.data,
    chainId,
  });
  const receipt = await tx.wait();
  if (!receipt || receipt.status !== 1) throw new Error('Payment transaction reverted');
  return { txHash: tx.hash, blockNumber: receipt.blockNumber };
}

/** `0x90F8…c9C1` for tables and badges; empty string for a missing address. */
export function shortAddress(a) {
  return a ? `${a.slice(0, 6)}…${a.slice(-4)}` : '';
}
