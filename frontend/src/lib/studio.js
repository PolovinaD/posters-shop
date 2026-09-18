// Pure helpers for the AI poster studio page. Same convention as
// src/lib/address.js: no JSX, no React import, so node can import this file
// directly and it stays testable without a browser.

/** Generation statuses that are still moving — the page keeps polling for these. */
export const IN_FLIGHT = ['queued', 'generating'];

/**
 * React Query `refetchInterval`: poll every 2 s only while a generation is in
 * flight; `false` stops the timer once the job is `ready` or `failed` (or the
 * status is unknown, e.g. before the first response arrives).
 *
 * @param {string|undefined} status
 * @returns {number|false}
 */
export function pollIntervalFor(status) {
  return IN_FLIGHT.includes(status) ? 2000 : false;
}

/**
 * Tailwind tone classes per status for the small badge on a design card.
 *
 * @param {string|undefined} status
 * @returns {string}
 */
export function statusTone(status) {
  switch (status) {
    case 'ready':
      return 'bg-emerald-100 text-emerald-800';
    case 'failed':
      return 'bg-red-100 text-red-800';
    case 'generating':
      return 'bg-amber-100 text-amber-800';
    default:
      return 'bg-stone-100 text-stone-700';
  }
}

/**
 * "3 of 10 today" | "Unlimited (owner)" | "" when the quota is not known yet.
 *
 * @param {{used?: number, limit?: number, exempt?: boolean}|null|undefined} quota
 * @returns {string}
 */
export function quotaLabel(quota) {
  if (!quota) return '';
  if (quota.exempt) return 'Unlimited (owner)';
  return `${quota.used} of ${quota.limit} today`;
}

/**
 * The prompt to put in the form when a saved prompt is reused — trimmed,
 * never undefined.
 *
 * @param {{prompt?: string}|null|undefined} saved
 * @returns {string}
 */
export function promptFromSaved(saved) {
  return (saved?.prompt ?? '').trim();
}

/**
 * Short display title for a design card: the first 48 characters of the prompt
 * with an ellipsis when it was cut.
 *
 * @param {{prompt?: string}|null|undefined} gen
 * @returns {string}
 */
export function cardTitle(gen) {
  const p = (gen?.prompt ?? '').trim();
  return p.length > 48 ? `${p.slice(0, 48)}…` : p;
}

/**
 * A Retry-After value as a human duration: "45 seconds" (singular "1 second"),
 * "2 min", "1 h", "6 h 7 min". Whole seconds under a minute; above that the
 * minutes are rounded UP so "try again in X" is never early (61 s → "2 min",
 * 21985 s = 6 h 6 min 25 s → "6 h 7 min"); a zero minutes part is omitted.
 * Anything that is not a non-negative number (null, "", "x", an HTTP-date)
 * → null.
 *
 * @param {number|string|null|undefined} seconds
 * @returns {string|null}
 */
export function formatWait(seconds) {
  if (seconds === null || seconds === undefined || seconds === '') return null;
  const s = Math.floor(Number(seconds));
  if (!Number.isFinite(s) || s < 0) return null;
  if (s < 60) return `${s} second${s === 1 ? '' : 's'}`;
  const minutes = Math.ceil(s / 60);
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m === 0 ? `${h} h` : `${h} h ${m} min`;
}

/**
 * "try again in 2 min" | "try again in 6 h 7 min (at 02:00)" — for waits
 * longer than an hour the reset is also given as a wall-clock time in the
 * reader's local zone, because "at 02:00" reads better than a countdown that
 * long. null when the wait is unknown (see formatWait).
 *
 * @param {number|string|null|undefined} seconds
 * @param {number} [now] epoch ms the wait counts from; defaults to Date.now()
 * @returns {string|null}
 */
export function retryAfterText(seconds, now = Date.now()) {
  const wait = formatWait(seconds);
  if (wait === null) return null;
  const s = Math.floor(Number(seconds));
  if (s <= 3600) return `try again in ${wait}`;
  const at = new Date(now + s * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  return `try again in ${wait} (at ${at})`;
}
