// Trends across sessions: the stats the chart can show, and its tooltip. ECharts sets a
// formatter's string as innerHTML, and a session's name is typed by the user (or taken from
// a folder on import), so everything from data is escaped here.
import type { Column, TrendSession } from '#lib/api.ts';
import { dateLabel, escapeHtml, fmtValue } from '#lib/format.ts';

export type TrendStat = 'winRate' | 'kdr' | 'deathsPerFight';

export interface TrendStatInfo {
	key: TrendStat;
	label: string;
	fmt: Column['fmt'];
	/** Text for a session without a value. */
	missing: string;
	hint: string;
}

export const TREND_STATS: TrendStatInfo[] = [
	{
		key: 'winRate',
		label: 'Win rate',
		fmt: 'pct',
		missing: 'skirmishes only',
		hint: 'Wins out of wins, evens and losses. Skirmishes (fewer than 3 deaths in total) are left out.'
	},
	{
		key: 'kdr',
		label: 'K/D',
		fmt: 'stacks',
		missing: 'no value',
		hint: 'Enemy deaths per squad death over the whole session.'
	},
	{
		key: 'deathsPerFight',
		label: 'Squad deaths per fight',
		fmt: 'int',
		missing: 'no value',
		hint: 'Squad deaths divided by analyzed fights. Lower is better.'
	}
];

/** A stat's value as text. K/D always gets two decimals, so a column of them lines up. */
export function fmtTrend(v: number | null | undefined, stat: TrendStatInfo): string {
	if (v == null) return stat.missing;
	return stat.key === 'kdr' ? v.toFixed(2) : fmtValue(v, stat.fmt);
}

/** The stat named in `?stat=`, or the first one. */
export function parseTrendStat(v: string | null | undefined): TrendStatInfo {
	return TREND_STATS.find((s) => s.key === v) ?? TREND_STATS[0];
}

/** "4W 1E 2L", plus "+1 skirmish" when there were any. */
export function resultsText(s: Pick<TrendSession, 'results'>): string {
	const r = s.results;
	const base = `${r.win ?? 0}W ${r.even ?? 0}E ${r.loss ?? 0}L`;
	const sk = r.skirmish ?? 0;
	return sk ? `${base} +${sk} skirmish${sk === 1 ? '' : 'es'}` : base;
}

export function sessionTooltipHtml(s: TrendSession, stat: TrendStatInfo): string {
	const v = s[stat.key];
	const lines = [
		`<b>${escapeHtml(dateLabel(s.start))}</b> ${escapeHtml(s.name)}`,
		`${escapeHtml(stat.label)}: <b>${escapeHtml(fmtTrend(v, stat))}</b>`,
		`${escapeHtml(s.fights)} fight${s.fights === 1 ? '' : 's'} · ${escapeHtml(resultsText(s))}`
	];
	if (s.topIssue) {
		lines.push(`Top problem: ${escapeHtml(s.topIssue.title)} (${escapeHtml(s.topIssue.count)} of ${escapeHtml(s.fights)})`);
	}
	lines.push('<span style="opacity:.65">Click to open the session</span>');
	return lines.join('<br/>');
}
