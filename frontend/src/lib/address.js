// Pure, framework-free helpers. `src/lib/` is the home for logic with no JSX and
// no React import, so node can import it directly and it stays testable without
// a browser — the repo has no frontend test runner.

/**
 * Turn a shipment's `shipping_address` object into display lines.
 *
 * The null guard and the blank filter are not defensive padding. Logistics'
 * `shipment_to_dict` emits `shipping_address: null` for every shipment created
 * before 260912-n7c's migration added the columns — at the time of writing that
 * is the majority of the rows in the local database, order 1 among them — so the
 * null path is the COMMON case here, not an edge case. Any field that is missing
 * or blank is dropped rather than stringified, which is what keeps "undefined",
 * "null" and "[object Object]" off a courier's screen.
 *
 * Postal code and city share one line, matching how OrderTracking.jsx renders
 * the customer's own copy of the same address.
 *
 * @param {object|null|undefined} address
 * @returns {string[]} display lines, empty when there is no address on file
 */
export function formatAddressLines(address) {
  if (!address) return [];
  const { recipient_name, street, city, postal_code, country, phone } = address;
  return [
    recipient_name,
    street,
    [postal_code, city].filter(Boolean).join(' '),
    country,
    phone,
  ].filter((line) => typeof line === 'string' && line.trim() !== '');
}
