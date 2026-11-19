<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { api, type Column, type SessionDetail } from '#lib/api.ts';
	import { live, toasts } from '#lib/live.svelte.ts';
	import { compact, dateLabel, duration, fmtValue, profColor } from '#lib/format.ts';
	import FightList from '#lib/components/FightList.svelte';
	import StatTable from '#lib/components/StatTable.svelte';
	import Badge, { severityBar } from '#lib/components/Badges.svelte';
	import Icon from '#lib/components/Icon.svelte';

	const id = $derived(Number(page.params.id));
	let data = $state<SessionDetail | null>(null);
	let loading = $state(true);
	let editing = $state(false);
	let name = $state('');
	let tab = $state<'summary' | 'players' | 'fights'>('summary');

	async function load() {
		try {
			data = await api.session(id);
			name = data.session.name;
		} catch (e) {
			toasts.error(e);
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		void id;
		loading = true;
		load();
	});

	onMount(() => {
		let t: ReturnType<typeof setTimeout> | null = null;
		return live.onFight((f) => {
			if (f.session_id !== id) return;
			if (t) clearTimeout(t);
			t = setTimeout(load, 1000);
		});
	});

	async function rename() {
		try {
			await api.renameSession(id, name);
			editing = false;
			load();
		} catch (e) {
			toasts.error(e);
		}
	}

	async function remove() {
		if (!confirm('Delete this session and its fights from the app? Their parsed data is deleted; your arcdps log files are kept.')) return;
		try {
			await api.deleteSession(id);
			goto('/sessions');
		} catch (e) {
			toasts.error(e);
		}
	}

	const gvgCount = $derived(data?.fights.filter((f) => f.mode === 'gvg').length ?? 0);
	const allGvg = $derived(!!data && data.fights.length > 0 && gvgCount === data.fights.length);

	async function switchMode() {
		const next = allGvg ? 'zerg' : 'gvg';
		const n = data?.fights.length ?? 0;
		if (!confirm(`Re-analyze all ${n} fights of this session as ${next === 'gvg' ? 'GvG rounds' : 'zerg fights'}?`)) return;
		try {
			const r = await api.setSessionMode(id, next);
			toasts.push(`Re-analyzing ${r.queued} fights as ${next === 'gvg' ? 'GvG' : 'zerg fights'}…`);
		} catch (e) {
			toasts.error(e);
		}
	}

	const agg = $derived(data?.aggregate);
	const totals = $derived(agg?.totals ?? {});
	const playerCols = $derived(
		['damage', 'down_contribution', 'against_downed', 'strips', 'cleanses', 'healing', 'barrier', 'gen_squadBuffs_1122', 'resurrects', 'downs', 'deaths', 'up_1122']
			.map((k) => agg?.columns.find((c) => c.key === k))
			.filter(Boolean) as Column[]
	);
	const boardFmt = (key: string) => agg?.columns.find((c) => c.key === key)?.fmt ?? 'num';
</script>

<div class="page">
	<a href="/sessions" class="mb-4 inline-flex items-center gap-1.5 text-sm text-muted hover:text-text">
		<Icon name="back" class="size-4" /> Sessions
	</a>

	{#if loading && !data}
		<div class="card h-40 animate-pulse"></div>
	{:else if data && agg}
		<div class="mb-5 flex flex-wrap items-start gap-4">
			<div>
				{#if editing}
					<form class="flex gap-2" onsubmit={(e) => (e.preventDefault(), rename())}>
						<input class="input w-80" bind:value={name} />
						<button class="btn btn-primary">Save</button>
						<button type="button" class="btn" onclick={() => (editing = false)}>Cancel</button>
					</form>
				{:else}
					<h1 class="flex items-center gap-2 text-2xl font-semibold">
						{data.session.name}
						<button class="text-faint hover:text-text" onclick={() => (editing = true)} title="Rename">
							<Icon name="settings" class="size-4" />
						</button>
						{#if data.recording}<span class="chip bg-loss/15 text-loss">● Live</span>{/if}
					</h1>
				{/if}
				<p class="mt-1 text-sm text-muted">
					{dateLabel(agg.fights[0]?.start ?? data.session.started_at)} · {totals.fights} analyzed fights · {duration(
						totals.durationS
					)} of fighting
				</p>
			</div>
			<div class="ml-auto flex gap-2">
				<button class="btn" onclick={switchMode}
					title={allGvg ? 'Analyze every fight of this session as a zerg fight' : 'Analyze every fight of this session as GvG rounds (call-offs are not counted)'}>
					<Icon name="swords" class="size-4" /> {allGvg ? 'Analyze session as zerg' : 'Analyze session as GvG'}
				</button>
				<button class="btn btn-ghost" onclick={remove} title="Delete session"><Icon name="trash" class="size-4" /></button>
			</div>
		</div>

		<div class="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
			<div class="card p-4">
				<div class="section-title">Results</div>
				<div class="tabular mt-2 text-lg font-semibold">
					<span class="text-win">{totals.results?.win ?? 0}W</span>
					<span class="text-even">{totals.results?.even ?? 0}E</span>
					<span class="text-loss">{totals.results?.loss ?? 0}L</span>
					<span class="text-sm font-normal text-faint">{totals.results?.skirmish ?? 0} skirmish</span>
				</div>
				{#if gvgCount}
					{@const gr = totals.gvgRounds ?? {}}
					<div class="mt-1 text-xs text-faint" title="Round results across the GvG fights of this session">
						GvG rounds: <span class="text-win">{gr.win ?? 0}W</span> <span class="text-even">{gr.even ?? 0}E</span>
						<span class="text-loss">{gr.loss ?? 0}L</span>
					</div>
				{/if}
			</div>
			<div class="card p-4">
				<div class="section-title">Kills / deaths</div>
				<div class="tabular mt-2 text-lg font-semibold">
					<span class="text-win">{totals.enemyDeaths}</span> / <span class="text-loss">{totals.squadDeaths}</span>
					<span class="text-sm font-normal text-faint">KDR {totals.kdr}</span>
				</div>
			</div>
			<div class="card p-4">
				<div class="section-title">Damage</div>
				<div class="tabular mt-2 text-lg font-semibold">{compact(totals.squadDamage)}</div>
			</div>
			<div class="card p-4">
				<div class="section-title">Players</div>
				<div class="tabular mt-2 text-lg font-semibold">{agg.players.length}</div>
			</div>
		</div>

		<div class="mb-4 flex gap-1 border-b border-line">
			{#each [['summary', 'Summary'], ['players', 'Players'], ['fights', 'Fights']] as [k, label]}
				<button
					class="-mb-px border-b-2 px-3.5 py-2 text-sm {tab === k ? 'border-accent font-medium text-text' : 'border-transparent text-muted hover:text-text'}"
					onclick={() => (tab = k as typeof tab)}>{label}</button
				>
			{/each}
		</div>

		{#if tab === 'summary'}
			<div class="grid gap-5 lg:grid-cols-5">
				<div class="space-y-3 lg:col-span-2">
					<h2 class="text-base font-semibold">Recurring problems</h2>
					{#if !agg.recurringIssues.length}
						<div class="card p-4 text-sm text-muted">No recurring problems.</div>
					{/if}
					<div class="card divide-y divide-line">
						{#each agg.recurringIssues.slice(0, 10) as r}
							<div class="flex items-center gap-3 px-4 py-3">
								<span class="h-8 w-1 rounded-full {severityBar[r.severity]}"></span>
								<div class="min-w-0 flex-1">
									<div class="truncate text-sm font-medium">{r.title}</div>
									<div class="mt-1 flex h-1.5 overflow-hidden rounded-full bg-raised">
										<div class="bg-accent/70" style="width:{r.share}%"></div>
									</div>
								</div>
								<div class="tabular text-right text-xs">
									<div class="text-text">{r.count}/{totals.fights} fights</div>
									<div class="text-faint">{r.losses} in losses</div>
								</div>
							</div>
						{/each}
					</div>
					{#if agg.positives.length}
						<h2 class="pt-2 text-base font-semibold">Strengths</h2>
						<div class="card divide-y divide-line">
							{#each agg.positives as r}
								<div class="flex items-center justify-between px-4 py-2.5 text-sm">
									<span class="flex items-center gap-2"><Icon name="check" class="size-4 text-win" />{r.title}</span>
									<span class="tabular text-xs text-faint">{r.count} fights</span>
								</div>
							{/each}
						</div>
					{/if}
				</div>
				<div class="lg:col-span-3">
					<h2 class="mb-3 text-base font-semibold">Leaderboards</h2>
					<div class="grid gap-3 md:grid-cols-2">
						{#each Object.entries(agg.leaderboards) as [key, board]}
							{#if board.rows.length}
								<div class="card p-4">
									<div class="mb-2 flex items-center gap-2">
										<Icon name="trophy" class="size-4 text-even" />
										<h3 class="text-sm font-semibold">{board.label}</h3>
										<span class="ml-auto text-[11px] text-faint">total · per fight</span>
									</div>
									<ol class="space-y-1.5">
										{#each board.rows.slice(0, 5) as r, i}
											<li class="flex items-center gap-2 text-sm">
												<span class="tabular w-4 text-xs text-faint">{i + 1}</span>
												<span class="size-2 shrink-0 rounded-full" style="background:{profColor(r.profession.split(', ')[0])}"></span>
												<span class="min-w-0 flex-1 truncate" title={r.account}>{r.name}</span>
												<span class="tabular font-medium">{fmtValue(r.total, boardFmt(key))}</span>
												<span class="tabular w-14 text-right text-xs text-faint">{fmtValue(r.perFight, boardFmt(key))}</span>
											</li>
										{/each}
									</ol>
								</div>
							{/if}
						{/each}
					</div>
				</div>
			</div>
		{:else if tab === 'players'}
			<StatTable columns={playerCols} players={agg.players} extraLead={{ key: 'fights', label: 'Fights' }} hideAbsent={false} />
			<p class="mt-2 text-xs text-faint">Summed over the session's fights (uptime averaged). One row per account.</p>
		{:else}
			<FightList fights={data.fights} showDate={false} />
		{/if}
	{/if}
</div>
