import type { Column, Result, Severity } from './api.ts';

const nf0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 });
const nf2 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 });

export function compact(v: number | null | undefined): string {
	if (v == null || !isFinite(v)) return '–';
	const a = Math.abs(v);
	if (a >= 1e6) return nf2.format(v / 1e6) + 'M';
	if (a >= 1e4) return nf0.format(v / 1e3) + 'k';
	if (a >= 1e3) return nf1.format(v / 1e3) + 'k';
	return nf0.format(v);
}

export function duration(s: number | null | undefined): string {
	if (s == null) return '–';
	const t = Math.round(s);
	const m = Math.floor(t / 60);
	return `${m}:${String(t % 60).padStart(2, '0')}`;
}

export function fmtValue(v: any, fmt: Column['fmt']): string {
	if (v == null || v === '') return '–';
	if (fmt === 'text') return String(v);
	const n = Number(v);
	if (!isFinite(n)) return '–';
	switch (fmt) {
		case 'num':
			return compact(n);
		case 'pct':
			return nf0.format(n) + '%';
		case 'stacks':
			return nf2.format(n);
		case 'dist':
			return nf0.format(n);
		case 'sec':
			return duration(n);
		default:
			return Number.isInteger(n) ? nf0.format(n) : nf1.format(n);
	}
}

/** Parse EI's "2026-11-17 20:21:55 +01:00" into a Date. */
export function parseStart(s: string | null | undefined): Date | null {
	if (!s) return null;
	const m = s.match(/^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})\s*([+-]\d{2}:?\d{2})?/);
	if (!m) {
		const d = new Date(s);
		return isNaN(+d) ? null : d;
	}
	const d = new Date(`${m[1]}T${m[2]}${m[3] ? m[3] : ''}`);
	return isNaN(+d) ? null : d;
}

export function timeOfDay(s: string | null | undefined): string {
	const d = parseStart(s);
	return d ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '–';
}

export function dateLabel(s: string | null | undefined): string {
	const d = parseStart(s);
	return d ? d.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' }) : '';
}

export const resultLabel: Record<Result, string> = {
	win: 'Win',
	loss: 'Loss',
	even: 'Even',
	skirmish: 'Skirmish'
};

export const severityLabel: Record<Severity, string> = {
	critical: 'Critical',
	major: 'Major',
	minor: 'Minor',
	info: 'Context',
	positive: 'Went well'
};

// Elite specialization -> core profession (for colors).
const SPEC_TO_PROF: Record<string, string> = {
	Guardian: 'Guardian', Dragonhunter: 'Guardian', Firebrand: 'Guardian', Willbender: 'Guardian', Luminary: 'Guardian',
	Warrior: 'Warrior', Berserker: 'Warrior', Spellbreaker: 'Warrior', Bladesworn: 'Warrior', Paragon: 'Warrior',
	Revenant: 'Revenant', Herald: 'Revenant', Renegade: 'Revenant', Vindicator: 'Revenant', Conduit: 'Revenant',
	Engineer: 'Engineer', Scrapper: 'Engineer', Holosmith: 'Engineer', Mechanist: 'Engineer', Amalgam: 'Engineer',
	Ranger: 'Ranger', Druid: 'Ranger', Soulbeast: 'Ranger', Untamed: 'Ranger', Galeshot: 'Ranger',
	Thief: 'Thief', Daredevil: 'Thief', Deadeye: 'Thief', Specter: 'Thief', Antiquary: 'Thief',
	Elementalist: 'Elementalist', Tempest: 'Elementalist', Weaver: 'Elementalist', Catalyst: 'Elementalist', Evoker: 'Elementalist',
	Mesmer: 'Mesmer', Chronomancer: 'Mesmer', Mirage: 'Mesmer', Virtuoso: 'Mesmer', Troubadour: 'Mesmer',
	Necromancer: 'Necromancer', Reaper: 'Necromancer', Scourge: 'Necromancer', Harbinger: 'Necromancer', Ritualist: 'Necromancer'
};

const PROF_COLOR: Record<string, string> = {
	Guardian: '#72c1d9',
	Warrior: '#ffd166',
	Revenant: '#d16e5a',
	Engineer: '#d09c59',
	Ranger: '#8cdc82',
	Thief: '#c08f95',
	Elementalist: '#f68a87',
	Mesmer: '#b679d5',
	Necromancer: '#52a76f'
};

/** Color of a spec. A session row lists several ("Firebrand, Willbender", most played first):
 * the first one gives the color. */
export function profColor(spec: string | null | undefined): string {
	const main = (spec ?? '').split(', ')[0];
	return PROF_COLOR[SPEC_TO_PROF[main] ?? ''] ?? '#8b94a8';
}

/** Text for HTML built by hand (ECharts tooltip formatters write their string as innerHTML):
 * names come from logs and must not become markup. */
export function escapeHtml(s: unknown): string {
	return String(s ?? '').replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}
