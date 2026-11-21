// Tooltip of the session trend chart. ECharts sets a formatter's string as innerHTML, and the
// series name holds a player's name from the log, so everything from data is escaped here.
import type { Column, Result } from '#lib/api.ts';
import { escapeHtml, fmtValue, timeOfDay } from '#lib/format.ts';

export const RESULT_COLORS: Record<Result, string> = {
	win: '#3ecf8e',
	loss: '#f2555a',
	even: '#e3c34f',
	skirmish: '#8a93a8'
};

export interface TrendTooltipFight {
	start: string | null;
	map: string | null;
	result: Result | null;
}

export interface TrendTooltipLine {
	/** ECharts' own colored dot (its HTML, not data). */
	marker: string;
	name: string;
	value: number | null;
	/** Text for a missing value (default: "not in this fight"). A player can be in a fight and
	 * still have no value, e.g. no distance to tag as the commander or without a tag. */
	missing?: string;
}

export function trendTooltipHtml(f: TrendTooltipFight, lines: TrendTooltipLine[], fmt: Column['fmt']): string {
	const color = (f.result && RESULT_COLORS[f.result]) || '#8a93a8';
	const head =
		`<b>${escapeHtml(timeOfDay(f.start))}</b> ${escapeHtml(f.map ?? '')} · ` +
		`<span style="color:${color}">${escapeHtml(f.result ?? '')}</span>`;
	const rows = lines.map(
		(l) => `${l.marker}${escapeHtml(l.name)}: <b>${l.value == null ? escapeHtml(l.missing ?? 'not in this fight') : escapeHtml(fmtValue(l.value, fmt))}</b>`
	);
	return [head, ...rows, '<span style="opacity:.65">Click to open the fight</span>'].join('<br/>');
}
