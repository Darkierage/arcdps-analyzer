// The session page's address, and where a fight page's "← Session" link goes: back to the
// session page as it was left (its tab, and the trend's player and stat), not its default view.
let last: { id: number; url: string } | null = null;

/** The session page calls this whenever its address changes. */
export function rememberSession(id: number, url: string): void {
	if (url.startsWith(`/sessions/${id}`)) last = { id, url };
}

export function sessionBackHref(id: number): string {
	return last?.id === id ? last.url : `/sessions/${id}`;
}

/** What the session page keeps in its address: the tab, and the trend's player and stat. */
export interface SessionView {
	tab: string;
	/** An account, or null for the squad or a party. */
	player: string | null;
	stat: string;
}

export const DEFAULT_TAB = 'summary';
export const DEFAULT_STAT = 'up_1122';

/** The view in a session address; unknown tabs and stats fall back to the defaults. */
export function parseSessionView(q: { get(k: string): string | null }, tabs: string[], stats: string[]): SessionView {
	const tab = q.get('tab');
	const stat = q.get('stat');
	return {
		tab: tab && tabs.includes(tab) ? tab : DEFAULT_TAB,
		player: q.get('player') || null,
		stat: stat && stats.includes(stat) ? stat : DEFAULT_STAT
	};
}

/** `base` with the view written in; defaults are left out, other parameters kept. */
export function sessionSearch(base: URLSearchParams, v: SessionView): URLSearchParams {
	const q = new URLSearchParams(base);
	for (const k of ['tab', 'player', 'stat']) q.delete(k);
	if (v.tab !== DEFAULT_TAB) q.set('tab', v.tab);
	if (v.player) q.set('player', v.player);
	if (v.stat !== DEFAULT_STAT) q.set('stat', v.stat);
	return q;
}
