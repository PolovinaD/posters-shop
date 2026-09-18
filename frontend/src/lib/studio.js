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
