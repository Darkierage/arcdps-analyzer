// Who went down or died near a point on a fight chart: the tooltip section shared by the fight
// timeline and the boon timeline (their markers alone only show when).
import type { EChartsType } from 'echarts/core';
import type { Timeline } from '#lib/api.ts';
import { duration, escapeHtml as esc, profColor } from '#lib/format.ts';

const MAX_LINES = 8;
const DOWN = '#f59e42';
const DEAD = '#f2555a';

type Chart = Pick<EChartsType, 'getZr' | 'convertToPixel' | 'convertFromPixel'>;

/** Which marker kinds are shown (a kind hidden in the chart's legend isn't listed either). */
export interface Shown {
	downs?: boolean;
	leftDowns?: boolean; // GvG: downs left at a call-off (hollow markers)
	deaths?: boolean;
	enemyDowns?: boolean;
	enemyDeaths?: boolean;
}

export interface EventOptions {
	/** Only this party's downs and deaths (group number as a string); null = the whole squad. */
	group?: string | null;
	/** Also count enemy downs and deaths (the fight timeline has an enemy lane). */
	enemies?: boolean;
	/** Player name -> profession, for deaths (death events carry no profession). */
	professions?: Record<string, string>;
	shown?: Shown;
}

/** Tooltip HTML for the downs and deaths within `tol` seconds of `x`; '' when there are none. */
export function eventsSection(tl: Timeline, x: number, tol: number, opts: EventOptions = {}): string {
	const on = (k: keyof Shown) => opts.shown?.[k] !== false;
	const near = (t: number) => Math.abs(t - x) <= tol;
	const mine = (g: number) => opts.group == null || String(g) === opts.group;
	const who = (name: string, prof: string) =>
		`<b style="color:${profColor(prof)}">${esc(name)}</b>` +
		(prof ? ` <span style="opacity:.65">${esc(prof)}</span>` : '');
	const rows: { t: number; html: string }[] = [];
	for (const d of tl.squadDowns) {
		if (!near(d.t) || !mine(d.group) || !on(d.left ? 'leftDowns' : 'downs')) continue;
		// A down left at a GvG call-off may never have ended: don't claim the player got up.
		const outcome = d.died ? 'died' : d.left ? 'left at call-off' : 'got up';
		const bits = [outcome, `${Math.round(d.stab)} stab`];
		if (d.dist_tag != null) bits.push(`${Math.round(d.dist_tag)} from tag`);
		if (d.left && d.died) bits.push('left at call-off');
		rows.push({
			t: d.t,
			html:
				`<span style="color:${DOWN}">▲</span> ${who(d.player, d.profession)} ` +
				`<span style="opacity:.65">· Party ${d.group} · ${duration(d.t)}</span> down — ${bits.join(' · ')}`
		});
	}
	if (on('deaths')) {
		for (const d of tl.squadDeaths) {
			if (!near(d.t) || !mine(d.group)) continue;
			rows.push({
				t: d.t,
				html:
					`<span style="color:${DEAD}">✕</span> ${who(d.player, opts.professions?.[d.player] ?? '')} ` +
					`<span style="opacity:.65">· Party ${d.group} · ${duration(d.t)}</span> died`
			});
		}
	}
	// Keep the ones closest to the pointer (the marker being hovered), then show them in time order.
	const kept = [...rows].sort((a, b) => Math.abs(a.t - x) - Math.abs(b.t - x)).slice(0, MAX_LINES);
	kept.sort((a, b) => a.t - b.t);
	const lines = kept.map((r) => r.html);
	if (rows.length > MAX_LINES) lines.push(`<span style="opacity:.65">+${rows.length - MAX_LINES} more nearby</span>`);
	if (opts.enemies) {
		const downs = on('enemyDowns') ? tl.enemyDowns.filter(near).length : 0;
		const deaths = on('enemyDeaths') ? tl.enemyDeaths.filter(near).length : 0;
		const n = (k: number, w: string) => `${k} ${w}${k === 1 ? '' : 's'}`;
		if (downs || deaths) lines.push(`Enemy: ${[downs && n(downs, 'down'), deaths && n(deaths, 'death')].filter(Boolean).join(', ')}`);
	}
	if (!lines.length) return '';
	return `<div style="margin-top:6px;padding-top:6px;border-top:1px solid #2c3550;max-width:520px;white-space:normal">${lines.join('<br/>')}</div>`;
}

/** The time under the mouse on the chart's first x axis. The axis tooltip's own params can't be
 * used for it: over the marker lane ECharts hands it the nearest marker's data, whose time may be
 * far from the pointer. The pixel is kept and converted on each call, so a mouse-wheel zoom
 * (which re-draws the tooltip without a mouse move) still gets the right time. */
export function trackPointer(chart: Chart): () => number | null {
	let px: number | null = null;
	chart.getZr().on('mousemove', (e) => {
		px = e.offsetX;
	});
	chart.getZr().on('globalout', () => {
		px = null;
	});
	return () => {
		if (px == null) return null;
		const v = Number(chart.convertFromPixel({ xAxisIndex: 0 }, px));
		return Number.isFinite(v) ? v : null;
	};
}

/** Seconds that `px` pixels span on the chart's first x axis at the current zoom. */
export function secondsPerPixels(chart: Chart | null, x: number, px = 8): number {
	if (!chart) return 1;
	const p = Number(chart.convertToPixel({ xAxisIndex: 0 }, x));
	const x2 = Number(chart.convertFromPixel({ xAxisIndex: 0 }, p + px));
	const s = Math.abs(x2 - x);
	return Number.isFinite(s) && s > 0 ? s : 1;
}
