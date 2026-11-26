<script lang="ts">
	// The session page's Videos tab: recordings linked to this session's fights (by time), files
	// found in the recording folders, and adding one by hand. Files are never copied or changed.
	import { api, type FightRow, type VideoRow, type VideoSuggestion } from '#lib/api.ts';
	import { live, toasts } from '#lib/live.svelte.ts';
	import { offsetLabel } from '#lib/videoSync.ts';
	import Icon from './Icon.svelte';

	let { sessionId, fights }: { sessionId: number; fights: FightRow[] } = $props();

	let videos = $state<VideoRow[]>([]);
	let suggestions = $state<VideoSuggestion[]>([]);
	let folders = $state<string[]>([]);
	let loading = $state(true);
	let path = $state('');
	let busy = $state(false);
	// pywebview exposes window.pywebview.api in the desktop window only.
	const desktop = typeof window !== 'undefined' && 'pywebview' in window;

	// Fight number in the session (1 = first), as on the Fights tab read oldest first.
	const order = $derived(
		new Map(
			[...fights]
				.filter((f) => f.status !== 'skipped')
				.sort((a, b) => String(a.fight_start ?? '').localeCompare(String(b.fight_start ?? '')) || a.id - b.id)
				.map((f, i) => [f.id, i + 1])
		)
	);

	function fightRange(ids: number[]): string {
		const n = ids.map((i) => order.get(i)).filter((x): x is number => x != null).sort((a, b) => a - b);
		if (!n.length) return 'no fights';
		const runs: string[] = [];
		let a = n[0], b = n[0];
		for (const x of n.slice(1)) {
			if (x === b + 1) b = x;
			else {
				runs.push(a === b ? `${a}` : `${a}–${b}`);
				a = b = x;
			}
		}
		runs.push(a === b ? `${a}` : `${a}–${b}`);
		return `${n.length === 1 ? 'fight' : 'fights'} ${runs.join(', ')}`;
	}

	const clock = (ms: number | null) =>
		ms == null ? '…' : new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

	async function load() {
		try {
			const r = await api.sessionVideos(sessionId);
			videos = r.videos;
			suggestions = r.suggestions;
			folders = r.folders;
		} catch (e) {
			toasts.error(e);
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		void sessionId;
		void fights.length;
		load();
	});

	async function add(paths: string[]) {
		busy = true;
		let ok = 0;
		try {
			for (const p of paths) {
				try {
					await api.addVideo(p);
					ok++;
				} catch (e) {
					toasts.error(e);
				}
			}
			if (ok) toasts.push(`Linked ${ok} video${ok === 1 ? '' : 's'}`, 'success');
			path = '';
			await load();
		} finally {
			busy = false;
		}
	}

	async function pick() {
		const picked: string[] = (await (window as any).pywebview?.api?.pick_videos?.()) ?? [];
		if (picked.length) await add(picked);
	}

	async function patch(v: VideoRow, p: { label?: string; offsetMs?: number; manual?: boolean }) {
		try {
			const row = await api.updateVideo(v.id, p);
			videos = videos.map((x) => (x.id === v.id ? { ...x, ...row } : x));
		} catch (e) {
			toasts.error(e);
		}
	}

	async function unlink(v: VideoRow) {
		if (!confirm(`Unlink ${v.name}? The video file itself is kept.`)) return;
		try {
			await api.deleteVideo(v.id);
			await load();
		} catch (e) {
			toasts.error(e);
		}
	}

	const sourceLabel: Record<string, string> = {
		obs: 'OBS',
		filename: 'file name',
		filetime: 'file time',
		manual: 'by hand'
	};
</script>

<div class="space-y-5">
	<div class="card p-4">
		<div class="mb-3 flex flex-wrap items-center gap-2">
			<h2 class="font-semibold">Linked videos</h2>
			<span class="text-xs text-faint">Each video plays on the fights it covers (fight page → Replay). Files stay where they are.</span>
		</div>
		{#if loading}
			<div class="h-16 animate-pulse rounded bg-panel-2/40"></div>
		{:else if !videos.length}
			<p class="text-sm text-muted">
				No video covers this session's fights yet. Add one below{live.recording ? '' : ', or connect OBS in Settings so recordings link themselves'}.
			</p>
		{:else}
			<ul class="divide-y divide-line">
				{#each videos as v (v.id)}
					<li class="flex flex-wrap items-center gap-x-3 gap-y-1.5 py-2.5 text-sm">
						<Icon name="video" class="size-4 shrink-0 text-accent" />
						<div class="min-w-0 flex-1">
							<div class="truncate font-medium" title={v.path ?? ''}>{v.name}</div>
							<div class="text-xs text-faint">
								{clock(v.startMs)}–{clock(v.endMs)} · {fightRange(v.fightIds ?? [])} · synced from {sourceLabel[v.syncSource]}{v.offsetMs ? ` ${offsetLabel(v.offsetMs)}` : ''}
								{#if v.approximate}<span class="chip ml-1 bg-major/15 text-major" title="The start time may be off: open a fight's Replay tab and use Sync here">approximate</span>{/if}
								{#if !v.path}<span class="chip ml-1 bg-accent/15 text-accent">recording…</span>{:else if !v.exists}<span class="chip ml-1 bg-loss/15 text-loss">file not found</span>{/if}
							</div>
						</div>
						<input
							class="input !w-36 !py-1 text-xs"
							placeholder="Label (e.g. Me)"
							value={v.label}
							onchange={(e) => patch(v, { label: e.currentTarget.value })}
							aria-label="Label"
						/>
						<div class="flex items-center gap-1" title="Move the video on the fights' clock: applies to every fight it covers">
							<button class="btn !px-1.5 !py-0.5 text-xs" onclick={() => patch(v, { offsetMs: v.offsetMs - 500, manual: true })}>−0.5s</button>
							<span class="tabular w-12 text-center text-xs text-muted">{offsetLabel(v.offsetMs)}</span>
							<button class="btn !px-1.5 !py-0.5 text-xs" onclick={() => patch(v, { offsetMs: v.offsetMs + 500, manual: true })}>+0.5s</button>
						</div>
						<button class="btn btn-ghost !p-1" title="Unlink (the file is kept)" aria-label="Unlink" onclick={() => unlink(v)}>
							<Icon name="trash" class="size-4" />
						</button>
					</li>
				{/each}
			</ul>
		{/if}
	</div>

	{#if suggestions.length}
		<div class="card p-4">
			<div class="mb-2 flex flex-wrap items-center gap-2">
				<h2 class="font-semibold">Recordings from this session</h2>
				<span class="text-xs text-faint">Found in your recording folders by their time.</span>
				<button class="btn btn-primary ml-auto !py-1 text-xs" disabled={busy} onclick={() => add(suggestions.map((s) => s.path))}>
					Link all {suggestions.length}
				</button>
			</div>
			<ul class="divide-y divide-line">
				{#each suggestions as s (s.path)}
					<li class="flex items-center gap-3 py-2 text-sm">
						<div class="min-w-0 flex-1">
							<div class="truncate" title={s.path}>{s.name}</div>
							<div class="text-xs text-faint">{clock(s.startMs)}–{clock(s.endMs)} · {fightRange(s.fightIds)}</div>
						</div>
						<button class="btn !py-1 text-xs" disabled={busy} onclick={() => add([s.path])}>Link</button>
					</li>
				{/each}
			</ul>
		</div>
	{/if}

	<div class="card p-4">
		<h2 class="mb-1 font-semibold">Add a video</h2>
		<p class="mb-3 text-xs text-faint">
			MP4, MKV, MOV or WebM. The start time comes from the file name (OBS, NVIDIA and Game Bar names work) or the file's
			creation time; fix it with the nudge buttons or "Sync here" on a fight's Replay tab.
		</p>
		<div class="flex flex-wrap gap-2">
			{#if desktop}
				<button class="btn btn-primary" disabled={busy} onclick={pick}><Icon name="folder" class="size-4" /> Choose video files…</button>
			{/if}
			<input class="input min-w-64 flex-1" placeholder={'C:\\Users\\…\\Videos\\2026-11-10 20-01-02.mp4'} bind:value={path}
				onkeydown={(e) => e.key === 'Enter' && path.trim() && add([path.trim()])} />
			<button class="btn" disabled={busy || !path.trim()} onclick={() => add([path.trim()])}>Add path</button>
		</div>
		<p class="mt-2 text-xs text-faint">
			Recording folders searched for suggestions: {folders.length ? folders.join(', ') : 'none found'}
			(<a class="text-accent hover:underline" href="/settings#videos">change in Settings</a>).
		</p>
	</div>
</div>
