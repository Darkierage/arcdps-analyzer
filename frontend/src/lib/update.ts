// In-app updater helpers (plan 17): what the banner shows. Pure, so `npm test` covers them.
import type { UpdateStatus } from './api.ts';

export type BannerKind = 'none' | 'unfinished' | 'available';

/** Which banner to show. `later` is the version the user hid with "Later" in this run. */
export function bannerKind(u: UpdateStatus | null, later: string | null): BannerKind {
	if (!u) return 'none';
	const v = u.latest?.version;
	// While an install runs, keep showing its progress even if it was skipped or hidden. A failed
	// download doesn't count: Later and Skip hide it like any other offer.
	const running = u.download?.state === 'downloading' || u.download?.state === 'ready';
	if (u.available && v && running) return 'available';
	// An update that didn't finish, unless a newer release than that one is offered.
	const newer = u.available && v && u.enabled && !(u.skipped || later === v) && v !== u.unfinished?.version;
	if (u.unfinished && !newer) return later === unfinishedKey(u.unfinished.version) ? 'none' : 'unfinished';
	if (!u.available || !v) return 'none';
	if (u.skipped || later === v) return 'none';
	// Checks turned off: no banner for a release found earlier (Settings still shows it).
	if (!u.enabled) return 'none';
	return 'available';
}

/** The "Later" value that hides the "did not finish" banner (until the app restarts). */
export function unfinishedKey(version: string): string {
	return `unfinished:${version}`;
}

export function fmtMb(bytes: number): string {
	return (bytes / (1024 * 1024)).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0);
}

/** "12 / 54 MB" or "12 MB" while the size is unknown. */
export function downloadProgress(d: { done: number; total: number }): string {
	return d.total > 0 ? `${fmtMb(d.done)} / ${fmtMb(d.total)} MB` : `${fmtMb(d.done)} MB`;
}

const LATER_KEY = 'wvw-update-later';

/** "Later" lasts until the app restarts: sessionStorage lives as long as the window. */
export function laterVersion(): string | null {
	try {
		return sessionStorage.getItem(LATER_KEY);
	} catch {
		return null;
	}
}

export function setLater(version: string): void {
	try {
		sessionStorage.setItem(LATER_KEY, version);
	} catch {
		/* storage unavailable: the banner just comes back on the next page load */
	}
}
