// Shared import flow for dropped / picked logs: check what's new, confirm big imports, upload.
import { goto } from '$app/navigation';
import { api } from './api.ts';
import { logDate } from './drop.ts';
import { toasts } from './live.svelte.ts';

/** Above this many new logs the user must confirm explicitly. */
export const CONFIRM_THRESHOLD = 20;
/** Rough Elite Insights + analysis time per log, for the estimate shown before importing. */
export const SECONDS_PER_LOG = 4;
const UPLOAD_CONCURRENCY = 4;

export interface ImportPlan {
	files: File[]; // new logs to upload
	known: number; // already imported
	knownIds: number[];
	from: Date | null;
	to: Date | null;
	days: number;
	minutes: number;
}

class Importer {
	phase = $state<'idle' | 'checking' | 'confirm' | 'uploading'>('idle');
	plan = $state<ImportPlan | null>(null);
	done = $state(0);
	total = $state(0);
	private cancelRequested = false;

	/** Entry point: called with every log the user dropped or picked. */
	async start(files: File[]) {
		if (!files.length) {
			toasts.push('No arcdps logs (.zevtc / .evtc) found in what you dropped', 'error');
			return;
		}
		if (this.phase !== 'idle') {
			toasts.push('An import is already in progress', 'info');
			return;
		}
		this.phase = 'checking';
		try {
			const { known } = await api.importCheck(files.map((f) => f.name));
			const fresh = files.filter((f) => !(f.name in known));
			const knownIds = files.filter((f) => f.name in known).map((f) => known[f.name]);
			if (!fresh.length) {
				this.phase = 'idle';
				if (files.length === 1) {
					toasts.push('This log is already imported - opening it', 'info');
					goto(`/fights/${knownIds[0]}`);
				} else toasts.push(`All ${files.length} logs are already imported`, 'info');
				return;
			}
			const dates = fresh.map(logDate).sort((a, b) => +a - +b);
			this.plan = {
				files: fresh,
				known: files.length - fresh.length,
				knownIds,
				from: dates[0] ?? null,
				to: dates[dates.length - 1] ?? null,
				days: new Set(dates.map((d) => d.toDateString())).size,
				minutes: Math.max(1, Math.ceil((fresh.length * SECONDS_PER_LOG) / 60))
			};
			if (fresh.length > CONFIRM_THRESHOLD) this.phase = 'confirm';
			else await this.upload();
		} catch (e) {
			this.phase = 'idle';
			toasts.error(e);
		}
	}

	/** User confirmed a big import. */
	confirm() {
		if (this.phase === 'confirm') this.upload();
	}

	/** Dismiss the confirmation, or stop uploading the rest. */
	cancel() {
		if (this.phase === 'confirm') {
			this.phase = 'idle';
			this.plan = null;
		} else if (this.phase === 'uploading') this.cancelRequested = true;
	}

	private async upload() {
		const plan = this.plan!;
		this.phase = 'uploading';
		this.cancelRequested = false;
		this.done = 0;
		this.total = plan.files.length;
		let added = 0;
		let notWvw = 0;
		let failed = 0;
		const ids: number[] = [];
		const queue = [...plan.files];
		const worker = async () => {
			while (queue.length && !this.cancelRequested) {
				const f = queue.shift()!;
				try {
					const r = await api.uploadLog(f);
					added += r.added;
					notWvw += r.notWvw ?? 0;
					ids.push(...r.fightIds);
				} catch (e) {
					failed++;
					if (failed <= 3) toasts.error(e);
				}
				this.done++;
			}
		};
		await Promise.all(Array.from({ length: UPLOAD_CONCURRENCY }, worker));
		const stopped = this.cancelRequested;
		this.phase = 'idle';
		this.plan = null;

		const parts = [];
		if (added) parts.push(`queued ${added} log${added === 1 ? '' : 's'} for analysis`);
		if (notWvw) parts.push(`${notWvw} non-WvW skipped`);
		if (plan.known) parts.push(`${plan.known} already imported`);
		if (failed) parts.push(`${failed} failed`);
		if (stopped) parts.push(`stopped after ${this.done} of ${this.total}`);
		const text = parts.join(' · ');
		toasts.push(text.charAt(0).toUpperCase() + text.slice(1), added ? 'success' : 'info', 6000);

		if (plan.files.length === 1 && plan.known === 0 && ids.length === 1) goto(`/fights/${ids[0]}`);
	}
}

export const importer = new Importer();
