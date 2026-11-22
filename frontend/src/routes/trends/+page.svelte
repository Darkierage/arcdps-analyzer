<script lang="ts">
	import { onMount } from 'svelte';
	import { goto, replaceState } from '$app/navigation';
	import { page } from '$app/state';
	import { api, type TrendSession } from '#lib/api.ts';
	import { live, toasts } from '#lib/live.svelte.ts';
	import { dateLabel, fmtValue } from '#lib/format.ts';
	import { severityClass } from '#lib/components/Badges.svelte';
	import TrendsChart from '#lib/components/TrendsChart.svelte';
	import { fmtTrend, parseTrendStat, TREND_STATS, type TrendStatInfo } from '#lib/trends.ts';

	/** Oldest first, as the chart reads left to right. */
	let sessions = $state<TrendSession[]>([]);
	let loading = $state(true);
	let stat = $state<TrendStatInfo>(TREND_STATS[0]);

	/** Newest first for the table. */
	const rows = $derived([...sessions].reverse());

	async function load() {
		try {
			sessions = (await api.trends()).sessions;
		} catch (e) {
			toasts.error(e);
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		// Deep link: ?stat=<key>. Read from the address bar (see the session page).
		stat = parseTrendStat(new URL(window.location.href).searchParams.get('stat'));
		load();
		let t: ReturnType<typeof setTimeout> | null = null;
		const off = live.on((e) => {
			if (e.type !== 'fight' && e.type !== 'recording') return;
			if (t) clearTimeout(t);
			t = setTimeout(load, 800);
		});
		return () => {
			if (t) clearTimeout(t);
			off();
		};
	});

	function setStat(key: string) {
		stat = parseTrendStat(key);
		const u = new URL(window.location.href);
		u.searchParams.set('stat', stat.key);
		replaceState(u, page.state);
	}

	const openSession = (id: number) => goto(`/sessions/${id}`);
</script>

<div class="page">
	<h1 class="text-xl font-semibold">Trends</h1>
	<p class="mt-0.5 mb-5 text-sm text-muted">How your raids went from session to session.</p>

	{#if loading}
		<div class="card h-40 animate-pulse"></div>
	{:else if !sessions.length}
		<div class="card px-6 py-14 text-center text-sm text-muted">
			No analyzed sessions yet. Record a raid or import logs, and each session becomes one point here.
		</div>
	{:else}
		<div class="card p-4">
			<div class="mb-1 flex flex-wrap items-center gap-3">
				<h2 class="section-title">Per session</h2>
				<div class="ml-auto">
					<select class="input py-1 text-xs" value={stat.key} onchange={(e) => setStat(e.currentTarget.value)} aria-label="Stat">
						{#each TREND_STATS as s}<option value={s.key}>{s.label}</option>{/each}
					</select>
				</div>
			</div>
			<TrendsChart {sessions} {stat} onsession={openSession} />
			<p class="mt-1 text-xs text-faint">
				One point per session, oldest on the left. {stat.hint}
				{#if sessions.length < 2}A trend needs at least two sessions; this is the first point.{/if}
				Click a session to open it.
			</p>
		</div>

		<div class="card mt-4 max-h-[60vh] overflow-auto">
			<table class="w-full text-sm">
				<thead class="sticky top-0 z-10 bg-panel text-left text-xs text-faint">
					<tr>
						<th class="px-4 py-2 font-medium">Session</th>
						<th class="px-3 py-2 text-right font-medium">Fights</th>
						<th class="px-3 py-2 font-medium">Results</th>
						<th class="px-3 py-2 text-right font-medium">Win rate</th>
						<th class="px-3 py-2 text-right font-medium">K/D</th>
						<th class="px-3 py-2 text-right font-medium">Deaths / fight</th>
						<th class="px-4 py-2 font-medium">Top recurring problem</th>
					</tr>
				</thead>
				<tbody>
					{#each rows as s (s.id)}
						<tr class="cursor-pointer border-t border-line hover:bg-panel-2" onclick={() => openSession(s.id)}>
							<td class="px-4 py-2">
								<a href="/sessions/{s.id}" class="font-medium hover:text-accent" onclick={(e) => e.stopPropagation()}>{s.name}</a>
								<div class="text-xs text-faint">{dateLabel(s.start)}</div>
							</td>
							<td class="tabular px-3 py-2 text-right">{s.fights}</td>
							<td class="tabular px-3 py-2 whitespace-nowrap">
								<span class="text-win">{s.results.win}W</span>
								<span class="text-even">{s.results.even}E</span>
								<span class="text-loss">{s.results.loss}L</span>
								{#if s.results.skirmish}<span class="text-faint" title="Skirmishes: fewer than 3 deaths in total">+{s.results.skirmish}S</span>{/if}
							</td>
							{#each TREND_STATS as st (st.key)}
								<td class="tabular px-3 py-2 text-right">{s[st.key] == null ? fmtValue(null, st.fmt) : fmtTrend(s[st.key], st)}</td>
							{/each}
							<td class="px-4 py-2">
								{#if s.topIssue}
									<span class="inline-flex items-center rounded-md px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset {severityClass[s.topIssue.severity]}">{s.topIssue.title}</span>
									<span class="ml-1 text-xs text-faint">{s.topIssue.count} of {s.fights} fights</span>
								{:else}
									<span class="text-xs text-faint">none</span>
								{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</div>
