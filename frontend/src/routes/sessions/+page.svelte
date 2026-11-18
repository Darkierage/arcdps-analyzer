<script lang="ts">
	import { onMount } from 'svelte';
	import { api, type SessionRow } from '#lib/api.ts';
	import { live, toasts } from '#lib/live.svelte.ts';
	import { dateLabel, timeOfDay } from '#lib/format.ts';
	import Icon from '#lib/components/Icon.svelte';

	let sessions = $state<SessionRow[]>([]);
	let loading = $state(true);

	async function load() {
		try {
			sessions = await api.sessions();
		} catch (e) {
			toasts.error(e);
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		load();
		let t: ReturnType<typeof setTimeout> | null = null;
		return live.on((e) => {
			if (e.type !== 'fight' && e.type !== 'recording') return;
			if (t) clearTimeout(t);
			t = setTimeout(load, 800);
		});
	});

	function bar(s: SessionRow) {
		const total = Math.max((s.wins ?? 0) + (s.losses ?? 0) + (s.evens ?? 0), 1);
		return {
			win: ((s.wins ?? 0) / total) * 100,
			even: ((s.evens ?? 0) / total) * 100,
			loss: ((s.losses ?? 0) / total) * 100
		};
	}
</script>

<div class="page">
	<h1 class="text-xl font-semibold">Sessions</h1>
	<p class="mt-0.5 mb-5 text-sm text-muted">Each recording, or each imported day, is one raid session.</p>

	{#if loading}
		<div class="card h-40 animate-pulse"></div>
	{:else if !sessions.length}
		<div class="card px-6 py-14 text-center text-sm text-muted">
			No sessions yet. Start a recording or import logs.
		</div>
	{:else}
		<div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
			{#each sessions as s (s.id)}
				{@const b = bar(s)}
				{@const isLive = live.recording?.recording && live.recording.sessionId === s.id}
				<a href="/sessions/{s.id}" class="card group p-4 transition hover:border-accent/50 hover:bg-panel-2">
					<div class="flex items-start gap-2">
						<div class="min-w-0 flex-1">
							<div class="truncate font-semibold">{s.name}</div>
							<div class="mt-0.5 text-xs text-faint">
								{dateLabel(s.first_fight ?? s.started_at)}
								{#if s.first_fight}· {timeOfDay(s.first_fight)}–{timeOfDay(s.last_fight)}{/if}
							</div>
						</div>
						{#if isLive}
							<span class="chip bg-loss/15 text-loss"><span class="size-1.5 animate-pulse rounded-full bg-loss"></span>Live</span>
						{:else}
							<span class="chip bg-raised text-faint">{s.kind === 'import' ? 'Imported' : 'Recorded'}</span>
						{/if}
					</div>
					<div class="mt-4 flex items-end justify-between">
						<div class="tabular text-sm">
							<span class="text-2xl font-semibold">{s.analyzed ?? 0}</span>
							<span class="text-muted"> fights</span>
						</div>
						<div class="tabular text-sm">
							<span class="text-win">{s.wins ?? 0}W</span>
							<span class="text-even">{s.evens ?? 0}E</span>
							<span class="text-loss">{s.losses ?? 0}L</span>
						</div>
					</div>
					<div class="mt-2 flex h-1.5 overflow-hidden rounded-full bg-raised">
						<div class="bg-win" style="width:{b.win}%"></div>
						<div class="bg-even" style="width:{b.even}%"></div>
						<div class="bg-loss" style="width:{b.loss}%"></div>
					</div>
					<div class="mt-3 flex items-center gap-1 text-xs text-accent opacity-0 transition group-hover:opacity-100">
						Open summary <Icon name="chevron" class="size-3.5" />
					</div>
				</a>
			{/each}
		</div>
	{/if}
</div>
