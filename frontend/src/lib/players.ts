// Picking one squad row for its own charts on a fight page.
import type { Row } from '#lib/api.ts';

/** A row's key for its own series. EI can split a player into several rows in one fight (e.g.
 * after a spec change); later rows get `account#2`... Fights analyzed before the key existed
 * use the account. */
export const seriesKey = (r: Row): string => r.series_key ?? r.account;

/** The row a `?player=` value means: a row key, or an account (links from the session trend),
 * then that account's in-fight row with the most active time. */
export function findSeriesRow(rows: Row[], wanted: string | null | undefined): Row | null {
	if (!wanted) return null;
	const exact = rows.find((r) => seriesKey(r) === wanted);
	if (exact) return exact;
	const same = rows.filter((r) => r.account === wanted);
	same.sort(
		(a, b) => Number(b.in_fight !== false) - Number(a.in_fight !== false) || (b.active_s ?? 0) - (a.active_s ?? 0)
	);
	return same[0] ?? null;
}
