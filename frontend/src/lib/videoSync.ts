// Fight time <-> video time. Times on the wall clock are UTC milliseconds.
//
//   video_t = fight_start + t - video_start - paused_before(t) + offset
//
// `offset` is the user's correction (nudge / "Sync here"), one value per video. Pauses are the
// wall-clock spans the recording was paused (known from OBS only).
import type { VideoRow } from './api.ts';

type Timing = Pick<VideoRow, 'startMs' | 'endMs' | 'offsetMs' | 'pauses'>;

/** Milliseconds of pause before the wall-clock moment `wall` (a moment inside a pause counts
 * up to that moment, so the video holds the last frame before the pause). */
export function pausedBefore(pauses: [number, number][], wall: number): number {
	let ms = 0;
	for (const [a, b] of pauses) {
		if (wall <= a) continue;
		ms += Math.min(wall, b) - a;
	}
	return ms;
}

/** Video seconds showing fight second `t` (may be outside the file: check `inFile`). */
export function videoTime(v: Timing, fightStartMs: number, t: number): number {
	const wall = fightStartMs + t * 1000;
	return (wall - v.startMs - pausedBefore(v.pauses, wall) + v.offsetMs) / 1000;
}

/** The offset that makes fight second `t` show at video second `videoT` ("Sync here"). */
export function offsetFor(v: Timing, fightStartMs: number, t: number, videoT: number): number {
	const base = videoTime({ ...v, offsetMs: 0 }, fightStartMs, t);
	return Math.round((videoT - base) * 1000);
}

/** Whether video second `vt` is inside a file of `durationS` seconds (unknown: assume yes). */
export function inFile(vt: number, durationS: number | null | undefined): boolean {
	return vt >= 0 && (durationS == null || !Number.isFinite(durationS) || vt <= durationS);
}

/** Why a video shows nothing at fight second `t`, for the note on its tile. */
export function outsideNote(vt: number, durationS: number | null | undefined): string | null {
	if (vt < 0) return `starts ${humanGap(-vt)} after this moment`;
	if (durationS != null && Number.isFinite(durationS) && vt > durationS) return `ends ${humanGap(vt - durationS)} before this moment`;
	return null;
}

function humanGap(s: number): string {
	if (s < 90) return `${Math.round(s)} s`;
	if (s < 5400) return `${Math.round(s / 60)} min`;
	return `${(s / 3600).toFixed(1)} h`;
}

/** Signed offset for display: "+1.5 s", "−0.5 s", "0 s". */
export function offsetLabel(ms: number): string {
	if (!ms) return '0 s';
	const s = Math.abs(ms) / 1000;
	return `${ms > 0 ? '+' : '−'}${Number.isInteger(s) ? s : s.toFixed(1)} s`;
}

/** Re-seek a follower video only when it drifted this far from the clock (seeking stutters). */
export const DRIFT_S = 0.25;
