// Live app state fed by the backend WebSocket (recording, queue, fight updates).
import { api, type CrashRecord, type FightMode, type FightRow, type LlmStatus, type ObsStatus, type QueueState, type RecordingState, type UpdateStatus } from './api.ts';

type Listener = (event: any) => void;

class Live {
	connected = $state(false);
	recording = $state<RecordingState | null>(null);
	queue = $state<QueueState>({ pending: 0, current: null });
	llm = $state<LlmStatus | null>(null);
	eiInstalled = $state(true);
	version = $state('');
	onboarded = $state<boolean | null>(null);
	fightMode = $state<FightMode>('zerg'); // mode given to newly added fights
	crashes = $state<CrashRecord[]>([]); // crashes / unexpected exits not dismissed yet
	dataDir = $state('');
	obs = $state<ObsStatus | null>(null);
	update = $state<UpdateStatus | null>(null); // in-app updater (banner, Settings)
	private listeners = new Set<Listener>();
	private ws: WebSocket | null = null;
	private retry = 0;
	private started = false;

	start() {
		if (this.started) return;
		this.started = true;
		this.refresh();
		this.connect();
	}

	async refresh() {
		try {
			const s = await api.status();
			this.recording = s.recording;
			this.queue = s.queue;
			this.llm = s.llm;
			this.eiInstalled = s.eiInstalled;
			this.version = s.version;
			this.onboarded = s.onboarded;
			this.fightMode = s.fightMode ?? 'zerg';
			this.crashes = s.crashes ?? [];
			this.dataDir = s.dataDir;
			this.obs = s.obs ?? null;
			this.update = await api.update();
		} catch {
			/* backend not up yet; the socket retry loop will refresh */
		}
	}

	private updateTimer: ReturnType<typeof setTimeout> | null = null;
	/** Re-read the update status shortly after recording or the queue changed (debounced: an
	 * import sends many queue events). Only while an update is on offer. */
	private refreshUpdateSoon() {
		if (!this.update?.available || this.updateTimer) return;
		this.updateTimer = setTimeout(async () => {
			this.updateTimer = null;
			try {
				this.update = await api.update();
			} catch {
				/* the next event or reconnect tries again */
			}
		}, 1000);
	}

	/** Subscribe to raw events; returns an unsubscribe function. */
	on(fn: Listener): () => void {
		this.listeners.add(fn);
		return () => this.listeners.delete(fn);
	}

	/** Convenience: called with every updated fight row. */
	onFight(fn: (f: FightRow) => void): () => void {
		return this.on((e) => e.type === 'fight' && fn(e.fight));
	}

	private connect() {
		const proto = location.protocol === 'https:' ? 'wss' : 'ws';
		const ws = new WebSocket(`${proto}://${location.host}/ws`);
		this.ws = ws;
		ws.onopen = () => {
			this.connected = true;
			this.retry = 0;
			this.refresh();
		};
		ws.onmessage = (msg) => {
			const e = JSON.parse(msg.data);
			if (e.type === 'hello') {
				this.recording = e.recording;
				this.queue = e.queue;
			} else if (e.type === 'recording') this.recording = e.recording;
			else if (e.type === 'queue') this.queue = e.queue;
			// Whether an update can be installed depends on recording and the queue.
			if (e.type === 'recording' || e.type === 'queue') this.refreshUpdateSoon();
			else if (e.type === 'llm') this.llm = e.llm;
			else if (e.type === 'obs') this.obs = e.obs;
			else if (e.type === 'update') this.update = e.update;
			for (const fn of this.listeners) fn(e);
		};
		ws.onclose = () => {
			this.connected = false;
			this.ws = null;
			const delay = Math.min(1000 * 2 ** this.retry++, 10000);
			setTimeout(() => this.connect(), delay);
		};
	}
}

export const live = new Live();

// Tiny toast store.
export interface Toast {
	id: number;
	kind: 'info' | 'error' | 'success';
	text: string;
}

class Toasts {
	items = $state<Toast[]>([]);
	private next = 1;
	push(text: string, kind: Toast['kind'] = 'info', ms = 4500) {
		const id = this.next++;
		this.items = [...this.items, { id, kind, text }];
		setTimeout(() => this.dismiss(id), ms);
	}
	error(e: unknown) {
		this.push(e instanceof Error ? e.message : String(e), 'error', 7000);
	}
	dismiss(id: number) {
		this.items = this.items.filter((t) => t.id !== id);
	}
}

export const toasts = new Toasts();
