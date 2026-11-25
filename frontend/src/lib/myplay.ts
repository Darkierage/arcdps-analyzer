// Helpers for the personal review ("My play"): scope picker, deep links, number formatting.
import type { MyNumber, ReviewScope } from '#lib/api.ts';
import { compact } from '#lib/format.ts';

export type ScopeKey = 'last' | 'last5' | 'days30' | 'all';

export const SCOPES: { key: ScopeKey; label: string }[] = [
	{ key: 'last', label: 'Last session' },
	{ key: 'last5', label: 'Last 5 sessions' },
	{ key: 'days30', label: 'Last 30 days' },
	{ key: 'all', label: 'All fights' }
];

export const DEFAULT_SCOPE: ScopeKey = 'last5';

export function parseScope(v: string | null | undefined): ScopeKey {
	return SCOPES.some((s) => s.key === v) ? (v as ScopeKey) : DEFAULT_SCOPE;
}

/** The API query for a scope picked on the page (`now` for "last 30 days"). */
export function scopeQuery(scope: ScopeKey, spec: string | null, now: Date = new Date()): ReviewScope {
	const q: ReviewScope = {};
	if (scope === 'last') q.sessions = 1;
	else if (scope === 'last5') q.sessions = 5;
	else if (scope === 'days30') {
		const d = new Date(now.getTime() - 30 * 86_400_000);
		q.from = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
	}
	if (spec) q.profession = spec;
	return q;
}

/** My play's own URL: ?player=, ?scope=, ?spec= (defaults left out). */
export function myPlaySearch(player: string | null, scope: ScopeKey, spec: string | null): string {
	const q = new URLSearchParams();
	if (player) q.set('player', player);
	if (scope !== DEFAULT_SCOPE) q.set('scope', scope);
	if (spec) q.set('spec', spec);
	const s = q.toString();
	return s ? `?${s}` : '';
}

/** A fight opened on one player's charts, at a moment (a down): ?player=<row key>&t=<s>. */
export function fightLink(fightId: number, player: string | null | undefined, t?: number | null): string {
	const q = new URLSearchParams();
	if (player) q.set('player', player);
	if (t != null) q.set('t', String(Math.round(t)));
	const s = q.toString();
	return `/fights/${fightId}${s ? `?${s}` : ''}`;
}

/** The highlighted window around a `?t=` moment on the fight timeline. */
export function momentWindow(t: string | null): [number, number] | null {
	const n = t == null || t === '' ? NaN : Number(t);
	return Number.isFinite(n) && n >= 0 ? [Math.max(0, n - 5), n + 2] : null;
}

export function fmtNumber(v: number | null | undefined, n: Pick<MyNumber, 'unit' | 'key'>): string {
	if (v == null) return '–';
	if (n.unit === '%') return `${Math.round(v)}%`;
	if (n.key === 'dist_tag') return `${Math.round(v)}`;
	if (n.unit === 'stacks') return v.toFixed(2);
	const num = Math.abs(v) >= 1000 ? compact(v) : Math.abs(v) >= 10 ? v.toFixed(0) : v.toFixed(2);
	return n.unit.startsWith('/') || n.unit.startsWith('s/') ? `${num} ${n.unit}` : num;
}

/** Is `you` better or worse than a reference, by more than `margin` (a share)? */
export function compare(you: number | null, ref: number | null, higherIsBetter: boolean | null, margin = 0.15): 'better' | 'worse' | null {
	if (you == null || ref == null || higherIsBetter == null || ref === 0) return null;
	const rel = (you - ref) / Math.abs(ref);
	if (Math.abs(rel) < margin) return null;
	return rel > 0 === higherIsBetter ? 'better' : 'worse';
}

export const trendLabel: Record<'better' | 'same' | 'worse', string> = {
	better: '↗ better lately',
	same: '→ steady',
	worse: '↘ worse lately'
};

export const trendClass: Record<'better' | 'same' | 'worse', string> = {
	better: 'text-win',
	same: 'text-faint',
	worse: 'text-loss'
};

export const JOB_LABEL: Record<string, string> = {
	damage: 'damage',
	strips: 'strips',
	cleanses: 'cleanses',
	healing: 'healing',
	stab: 'stability'
};
