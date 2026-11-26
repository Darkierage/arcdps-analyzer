// Pure helpers for the combat replay (positions over time) and the shared playback clock.
import type { ReplayActor } from './api.ts';

export type ActorState = 'up' | 'down' | 'dead' | 'dc' | 'absent';

function inside(iv: [number, number][], t: number): boolean {
	for (const [a, b] of iv) if (t >= a && t < b) return true;
	return false;
}

/** An actor's state at `t` ms: outside its samples it is absent (not loaded in by arcdps). */
export function stateAt(a: ReplayActor, t: number): ActorState {
	if (t < a.start || t > a.end || a.p.length === 0) return 'absent';
	if (inside(a.dc, t)) return 'dc';
	if (inside(a.dead, t)) return 'dead';
	if (inside(a.down, t)) return 'down';
	return 'up';
}

/** Interpolated position at `t` ms (samples every `pollMs` from `a.start`); null when absent. */
export function positionAt(a: ReplayActor, t: number, pollMs: number): [number, number] | null {
	const n = a.p.length / 2;
	if (n === 0 || t < a.start || t > a.end) return null;
	const f = Math.max(0, (t - a.start) / pollMs);
	const i = Math.min(Math.floor(f), n - 1);
	const j = Math.min(i + 1, n - 1);
	const k = Math.min(1, f - i);
	return [a.p[2 * i] + (a.p[2 * j] - a.p[2 * i]) * k, a.p[2 * i + 1] + (a.p[2 * j + 1] - a.p[2 * i + 1]) * k];
}

/** Facing in degrees at `t` ms (nearest sample), or null. */
export function facingAt(a: ReplayActor, t: number, pollMs: number): number | null {
	if (!a.o.length || t < a.start || t > a.end) return null;
	const i = Math.min(Math.max(0, Math.round((t - a.start) / pollMs)), a.o.length - 1);
	return a.o[i];
}

/** Bounding box [minX, minY, maxX, maxY] of the given actors' positions (the squad's fight area). */
export function bounds(actors: ReplayActor[]): [number, number, number, number] | null {
	let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
	for (const a of actors) {
		for (let i = 0; i < a.p.length; i += 2) {
			const x = a.p[i], y = a.p[i + 1];
			if (x < x0) x0 = x;
			if (x > x1) x1 = x;
			if (y < y0) y0 = y;
			if (y > y1) y1 = y;
		}
	}
	return Number.isFinite(x0) ? [x0, y0, x1, y1] : null;
}

/** Where a timeline click opens the replay: `lead` seconds before the moment, not before 0. */
export function jumpTarget(t: number, leadS: number): number {
	return Math.max(0, t - Math.max(0, leadS));
}

/** Format seconds as m:ss.s for the replay clock. */
export function clockLabel(s: number): string {
	const t = Math.max(0, s);
	const m = Math.floor(t / 60);
	const r = t - m * 60;
	return `${m}:${r.toFixed(1).padStart(4, '0')}`;
}

/**
 * The shared playback clock of the Replay tab: the map and every video follow it. Time is in
 * fight seconds; it runs at `rate` while playing and stops at `end`.
 */
export class Clock {
	private base = 0; // fight time at the last (re)start
	private since = 0; // performance.now() at the last (re)start
	playing = false;
	rate = 1;
	end: number;
	private now: () => number;
	constructor(end: number, now: () => number = () => performance.now()) {
		this.end = end;
		this.now = now;
	}

	time(): number {
		if (!this.playing) return this.base;
		const t = this.base + ((this.now() - this.since) / 1000) * this.rate;
		if (t >= this.end) {
			this.base = this.end;
			this.playing = false;
			return this.end;
		}
		return t;
	}

	seek(t: number) {
		this.base = Math.min(Math.max(0, t), this.end);
		this.since = this.now();
	}

	play() {
		if (this.playing) return;
		if (this.base >= this.end) this.base = 0;
		this.since = this.now();
		this.playing = true;
	}

	pause() {
		this.base = this.time();
		this.playing = false;
	}

	setRate(r: number) {
		this.base = this.time();
		this.since = this.now();
		this.rate = r;
	}
}
