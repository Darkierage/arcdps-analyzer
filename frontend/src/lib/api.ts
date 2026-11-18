// Typed client for the Python backend.

export type Result = 'win' | 'loss' | 'even' | 'skirmish';
export type Severity = 'critical' | 'major' | 'minor' | 'positive' | 'info';
export type FightStatus = 'queued' | 'parsing' | 'analyzing' | 'done' | 'skipped' | 'failed';

export interface Summary {
	logId?: string;
	map?: string;
	start?: string;
	durationS?: number;
	squadCount?: number;
	squadInFight?: number;
	allyCount?: number;
	enemyCount?: number;
	outnumberRatio?: number | null;
	squadDowns?: number;
	squadDeaths?: number;
	enemyDowns?: number;
	enemyDeaths?: number;
	squadDamage?: number;
	squadDamageTaken?: number;
	squadStrips?: number;
	squadCleanses?: number;
	squadBoonsLost?: number;
	squadHealing?: number;
	hasHealData?: boolean;
	commander?: string | null;
	pov?: string;
	result?: Result;
	engage?: [number, number];
	topIssue?: string | null;
	topSeverity?: Severity | null;
	parties?: number[];
}

export interface FightRow {
	id: number;
	session_id: number | null;
	log_path: string;
	log_name: string;
	status: FightStatus;
	error: string | null;
	fight_start: string | null;
	result: Result | null;
	summary: Summary | null;
	created_at: string;
	updated_at: string;
}

export interface Column {
	key: string;
	label: string;
	tab: string;
	agg: 'sum' | 'mean' | 'max';
	fmt: 'int' | 'num' | 'pct' | 'stacks' | 'dist' | 'sec' | 'text';
	higherIsBetter: boolean | null;
	group: string | null;
	description: string;
}

export type Row = Record<string, any>;

export interface DownEvent {
	t: number;
	player: string;
	profession: string;
	group: number;
	died: boolean;
	stab: number;
	resist: boolean;
	boons: number;
	conditions: number;
	dist_tag: number | null;
	dist_stack: number | null;
}

export type Series = Record<string, (number | null)[]>;

export interface Timeline {
	t: number[];
	squad: Series;
	parties: Record<string, Series>;
	squadDowns: DownEvent[];
	squadDeaths: { t: number; player: string; group: number }[];
	enemyDowns: number[];
	enemyDeaths: number[];
	engage: [number, number];
}

export interface Stats {
	summary: Summary;
	columns: Column[];
	players: Row[];
	parties: Row[];
	squad: Row;
	timeline: Timeline;
	enemies: { count: number; professions: { profession: string; count: number }[] };
}

export interface Finding {
	detector: string;
	key: string;
	severity: Severity;
	impact: number;
	window: [number, number] | null;
	subjects: string[];
	evidence: Record<string, any>;
	title: string;
	cause: string;
	fix: string;
	related: string[];
}

export interface Notes {
	issues: Finding[];
	more: Finding[];
	positives: Finding[];
}

export interface FightDetail {
	fight: FightRow;
	stats: Stats | null;
	notes: Notes | null;
	debrief: string | null;
	debriefUnverified: string[];
	debriefAt: string | null;
}

export interface SessionRow {
	id: number;
	name: string;
	kind: 'recording' | 'import';
	started_at: string;
	ended_at: string | null;
	fights: number;
	analyzed: number | null;
	wins: number | null;
	losses: number | null;
	evens: number | null;
	first_fight: string | null;
	last_fight: string | null;
}

export interface RecurringIssue {
	key: string;
	title: string;
	count: number;
	share: number;
	losses: number;
	severity: Severity;
	fights: number[];
}

export interface SessionAggregate {
	fights: {
		id: number;
		map: string;
		start: string;
		result: Result;
		durationS: number;
		squadDeaths: number;
		enemyDeaths: number;
		squadCount: number;
		enemyCount: number;
		topIssue: string | null;
	}[];
	totals: Record<string, any>;
	players: Row[];
	columns: Column[];
	leaderboards: Record<
		string,
		{
			label: string;
			rows: {
				account: string;
				name: string;
				profession: string;
				fights: number;
				total: number;
				perFight: number;
			}[];
		}
	>;
	recurringIssues: RecurringIssue[];
	positives: RecurringIssue[];
}

export interface SessionDetail {
	session: SessionRow;
	aggregate: SessionAggregate;
	fights: FightRow[];
	recording: boolean;
}

export interface RecordingState {
	recording: boolean;
	sessionId: number | null;
	startedAt: number | null;
	fights: number;
	autoStarted: boolean;
	logDir: string | null;
	logDirOk: boolean;
}

export interface QueueState {
	pending: number;
	current: number | null;
	cancellable?: number;
}

export interface LlmStatus {
	enabled: boolean;
	serverInstalled: boolean;
	modelInstalled: boolean;
	model: string;
	running: boolean;
	busy: boolean;
	setup: { running: boolean; error: string | null; progress: number | null; step?: string };
	models: string[];
}

export interface ImportResult {
	added: number;
	alreadyKnown: number;
	fightIds: number[];
	notWvw?: number;
}

export interface RangeImport {
	folder?: string;
	since?: string;
	until?: string;
}

export interface AppStatus {
	version: string;
	recording: RecordingState;
	queue: QueueState;
	eiInstalled: boolean;
	eiPath: string;
	llm: LlmStatus;
	dataDir: string;
}

export interface DetectorInfo {
	name: string;
	label: string;
	description: string;
	defaults: Record<string, number | boolean>;
	enabled: boolean;
	config: Record<string, number | boolean>;
}

export interface SettingsResponse {
	settings: any;
	detectors: DetectorInfo[];
	resolvedLogDir: string;
	defaultLogDir: string;
	resolvedEiPath: string;
	templatesFile: string;
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
	const res = await fetch(url, {
		method,
		headers: body !== undefined ? { 'content-type': 'application/json' } : undefined,
		body: body !== undefined ? JSON.stringify(body) : undefined
	});
	if (!res.ok) {
		let detail = res.statusText;
		try {
			detail = (await res.json()).detail ?? detail;
		} catch {
			/* not JSON */
		}
		throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
	}
	return res.json() as Promise<T>;
}

export const api = {
	status: () => request<AppStatus>('GET', '/api/status'),
	startRecording: (name?: string) =>
		request<RecordingState>('POST', '/api/recording/start', { name: name || null }),
	stopRecording: () => request<RecordingState>('POST', '/api/recording/stop'),
	importLogs: (body: { folder?: string; since?: string; until?: string }) =>
		request<ImportResult>('POST', '/api/import', body),
	uploadLog: async (file: File): Promise<ImportResult> => {
		const res = await fetch(`/api/import/upload?filename=${encodeURIComponent(file.name)}`, {
			method: 'POST',
			headers: { 'content-type': 'application/octet-stream' },
			body: file
		});
		if (!res.ok) {
			let detail = res.statusText;
			try {
				detail = (await res.json()).detail ?? detail;
			} catch {
				/* not JSON */
			}
			throw new Error(`${file.name}: ${detail}`);
		}
		return res.json();
	},
	importPreview: (body: { folder?: string; since?: string; until?: string }) =>
		request<{ new: number; alreadyKnown: number; notWvw: number; days: number; from: string | null; to: string | null }>(
			'POST',
			'/api/import/preview',
			body
		),
	importCheck: (names: string[]) =>
		request<{ known: Record<string, number> }>('POST', '/api/import/check', { names }),
	cancelQueue: () => request<{ cancelled: number }>('POST', '/api/queue/cancel'),
	sessions: () => request<SessionRow[]>('GET', '/api/sessions'),
	session: (id: number) => request<SessionDetail>('GET', `/api/sessions/${id}`),
	renameSession: (id: number, name: string) =>
		request<SessionRow>('PATCH', `/api/sessions/${id}`, { name }),
	deleteSession: (id: number) => request<{ ok: boolean }>('DELETE', `/api/sessions/${id}`),
	fights: (params: { sessionId?: number | null; includeSkipped?: boolean } = {}) => {
		const q = new URLSearchParams();
		if (params.sessionId != null) q.set('session_id', String(params.sessionId));
		if (params.includeSkipped) q.set('include_skipped', 'true');
		return request<FightRow[]>('GET', `/api/fights?${q}`);
	},
	fight: (id: number) => request<FightDetail>('GET', `/api/fights/${id}`),
	reanalyze: (id: number, reparse = false) =>
		request<{ ok: boolean }>('POST', `/api/fights/${id}/reanalyze?reparse=${reparse}`),
	reanalyzeAll: () => request<{ queued: number }>('POST', '/api/reanalyze-all'),
	deleteFight: (id: number) => request<{ ok: boolean }>('DELETE', `/api/fights/${id}`),
	debrief: (id: number) =>
		request<{ text: string; unverified: string[] }>('POST', `/api/fights/${id}/debrief`),
	settings: () => request<SettingsResponse>('GET', '/api/settings'),
	saveSettings: (patch: unknown) => request<SettingsResponse>('PUT', '/api/settings', patch),
	llmSetup: () => request<LlmStatus>('POST', '/api/llm/setup'),
	llmUnload: () => request<LlmStatus>('POST', '/api/llm/unload')
};
