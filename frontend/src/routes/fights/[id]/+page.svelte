<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { api, type Column, type FightDetail } from '#lib/api.ts';
	import { live, toasts } from '#lib/live.svelte.ts';
	import { compact, dateLabel, duration, fmtValue, profColor, timeOfDay } from '#lib/format.ts';
	import Badge from '#lib/components/Badges.svelte';
	import FindingCard from '#lib/components/FindingCard.svelte';
	import FightTimeline from '#lib/components/FightTimeline.svelte';
	import StatTable from '#lib/components/StatTable.svelte';
	import Icon from '#lib/components/Icon.svelte';

	const id = $derived(Number(page.params.id));
	let data = $state<FightDetail | null>(null);
	let loading = $state(true);
	let tab = $state('debrief');
	let highlight = $state<[number, number] | null>(null);
	let partyLines = $state(false);
	let mode = $state<'player' | 'party'>('player');
	let hideAbsent = $state(true);
	let boonGroup = $state('Uptime');
	let showMore = $state(false);
	let debriefBusy = $state(false);

	async function load() {
		try {
			data = await api.fight(id);
		} catch (e) {
			toasts.error(e);
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		const unsub = live.on((e) => {
			if (e.type === 'fight' && e.fight.id === id) {
				if (e.fight.status === 'done' || e.fight.status === 'skipped' || e.fight.status === 'failed') load();
				else if (data) data.fight = e.fight;
			}
			if (e.type === 'debrief' && e.fightId === id) load();
		});
		return unsub;
	});

	$effect(() => {
		void id;
		loading = true;
		highlight = null;
		load();
	});

	const s = $derived(data?.fight.summary ?? data?.stats?.summary ?? null);
	const stats = $derived(data?.stats ?? null);
	const notes = $derived(data?.notes ?? null);
	const cols = (tabName: string, group?: string) =>
		(stats?.columns ?? []).filter((c: Column) => c.tab === tabName && (group === undefined || c.group === group));

	const boonGroups = ['Uptime', 'Self generation', 'Group generation', 'Off-group generation', 'Squad generation'];
	const tabs = [
		{ id: 'debrief', label: 'Debrief' },
		{ id: 'overview', label: 'Overview' },
		{ id: 'boons', label: 'Boons' },
		{ id: 'offense', label: 'Offense' },
		{ id: 'support', label: 'Support' },
		{ id: 'defense', label: 'Defense' },
		{ id: 'positioning', label: 'Positioning' }
	];

	const overviewCols = $derived(
		['damage', 'down_contribution', 'strips', 'cleanses', 'healing', 'up_1122', 'up_26980', 'downs', 'deaths', 'fight_dist_tag']
			.map((k) => stats?.columns.find((c) => c.key === k) ?? (k === 'fight_dist_tag'
				? ({ key: k, label: 'Dist. to tag (fight)', tab: 'positioning', agg: 'mean', fmt: 'dist', higherIsBetter: false, group: null, description: 'Median distance to the tag while up during the fight.' } as Column)
				: null))
			.filter(Boolean) as Column[]
	);

	const headline = $derived(
		s?.result === 'loss' ? 'Why this fight was lost' : s?.result === 'win' ? 'What to improve' : 'Key issues'
	);

	async function reanalyze(reparse = false) {
		try {
			await api.reanalyze(id, reparse);
			toasts.push(reparse ? 'Re-parsing log…' : 'Re-analyzing…');
		} catch (e) {
			toasts.error(e);
		}
	}

	async function remove() {
		if (!confirm('Remove this fight from the app? Its parsed data is deleted; your arcdps log file is kept.')) return;
		await api.deleteFight(id);
		goto('/');
	}

	async function writeDebrief() {
		debriefBusy = true;
		try {
			await api.debrief(id);
			await load();
		} catch (e) {
			toasts.error(e);
		} finally {
			debriefBusy = false;
		}
	}
</script>

<div class="page">
	<a href="/" class="mb-4 inline-flex items-center gap-1.5 text-sm text-muted hover:text-text">
		<Icon name="back" class="size-4" /> Fights
	</a>

	{#if loading && !data}
		<div class="card h-40 animate-pulse"></div>
	{:else if data}
		{@const f = data.fight}
		<!-- Header -->
		<div class="mb-5 flex flex-wrap items-start gap-4">
			<div class="min-w-0">
				<div class="flex items-center gap-3">
					<h1 class="text-2xl font-semibold">{s?.map ?? f.log_name}</h1>
					{#if f.status === 'done' && f.result}<Badge result={f.result} size="lg" />{:else}<Badge status={f.status} size="lg" />{/if}
				</div>
				<div class="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
					<span>{dateLabel(s?.start)} {timeOfDay(s?.start)}</span>
					<span class="text-faint">·</span>
					<span class="tabular">{duration(s?.durationS)}</span>
					{#if s?.commander}<span class="text-faint">·</span><span>Tag: {s.commander}</span>{/if}
					{#if s?.pov}<span class="text-faint">·</span><span>Log by {s.pov}</span>{/if}
					<span class="text-faint">·</span><span class="text-faint">{f.log_name}</span>
				</div>
			</div>
			<div class="ml-auto flex gap-2">
				<button class="btn" onclick={() => reanalyze(false)} title="Run detectors again (e.g. after changing thresholds)">
					<Icon name="refresh" class="size-4" /> Re-analyze
				</button>
				<button class="btn btn-ghost" onclick={remove} title="Remove from app"><Icon name="trash" class="size-4" /></button>
			</div>
		</div>

		{#if f.status !== 'done'}
			<div class="card p-6 text-sm">
				{#if f.status === 'skipped'}
					<p class="text-muted">This log was skipped: <b class="text-text">{f.error}</b>.</p>
					<p class="mt-1 text-faint">Change the filters in Settings and re-analyze if you want it included.</p>
					<button class="btn mt-3" onclick={() => reanalyze(false)}>Re-analyze</button>
				{:else if f.status === 'failed'}
					<p class="text-loss">Processing failed: {f.error}</p>
					<button class="btn mt-3" onclick={() => reanalyze(true)}>Retry (re-parse)</button>
				{:else}
					<p class="flex items-center gap-2 text-muted"><Badge status={f.status} /> The log is being processed…</p>
				{/if}
			</div>
		{:else if stats && notes && s}
			<!-- Scoreboard -->
			<div class="mb-5 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
				<div class="card p-3.5">
					<div class="section-title">Numbers</div>
					<div class="tabular mt-1.5 text-lg font-semibold">
						{s.squadInFight ?? s.squadCount}{#if s.allyCount}<span class="text-sm text-faint"> +{s.allyCount}</span>{/if}
						<span class="text-sm font-normal text-faint">vs</span>
						<span class={(s.outnumberRatio ?? 0) >= 1.3 ? 'text-major' : ''}>{s.enemyCount}</span>
					</div>
					<div class="text-xs text-faint">{s.outnumberRatio ? `${s.outnumberRatio}x enemy ratio` : ''}</div>
				</div>
				<div class="card p-3.5">
					<div class="section-title">Kills / deaths</div>
					<div class="tabular mt-1.5 text-lg font-semibold">
						<span class="text-win">{s.enemyDeaths}</span> <span class="text-faint">/</span> <span class="text-loss">{s.squadDeaths}</span>
					</div>
					<div class="text-xs text-faint">downs {s.enemyDowns} / {s.squadDowns}</div>
				</div>
				<div class="card p-3.5">
					<div class="section-title">Damage</div>
					<div class="tabular mt-1.5 text-lg font-semibold">{compact(s.squadDamage)}</div>
					<div class="text-xs text-faint">taken {compact(s.squadDamageTaken)}</div>
				</div>
				<div class="card p-3.5">
					<div class="section-title">Strips</div>
					<div class="tabular mt-1.5 text-lg font-semibold">{compact(s.squadStrips)}</div>
					<div class="text-xs {(s.squadBoonsLost ?? 0) > (s.squadStrips ?? 0) ? 'text-loss' : 'text-faint'}">
						boons lost {compact(s.squadBoonsLost)}
					</div>
				</div>
				<div class="card p-3.5">
					<div class="section-title">Cleanses</div>
					<div class="tabular mt-1.5 text-lg font-semibold">{compact(s.squadCleanses)}</div>
					<div class="text-xs text-faint">to allies</div>
				</div>
				<div class="card p-3.5">
					<div class="section-title">Healing</div>
					<div class="tabular mt-1.5 text-lg font-semibold">{s.hasHealData ? compact(s.squadHealing) : '–'}</div>
					<div class="text-xs text-faint">{s.hasHealData ? 'from addon users' : 'no heal addon data'}</div>
				</div>
			</div>

			<!-- Tabs -->
			<div class="mb-4 flex gap-1 border-b border-line">
				{#each tabs as t}
					<button
						class="-mb-px border-b-2 px-3.5 py-2 text-sm transition {tab === t.id
							? 'border-accent font-medium text-text'
							: 'border-transparent text-muted hover:text-text'}"
						onclick={() => (tab = t.id)}
					>
						{t.label}
					</button>
				{/each}
			</div>

			{#if tab === 'debrief'}
				<div class="card mb-5 p-4">
					<div class="mb-1 flex items-center gap-3">
						<h2 class="section-title">Fight timeline</h2>
						<label class="ml-auto flex items-center gap-2 text-xs text-muted">
							<input type="checkbox" class="accent-accent" bind:checked={partyLines} /> Stability per party
						</label>
					</div>
					<FightTimeline timeline={stats.timeline} {highlight} {partyLines} />
				</div>

				<div class="grid gap-5 lg:grid-cols-3">
					<div class="space-y-3 lg:col-span-2">
						<h2 class="text-base font-semibold">{headline}</h2>
						{#if notes.issues.length === 0}
							<div class="card p-5 text-sm text-muted">No significant problems detected in this fight.</div>
						{/if}
						{#each notes.issues as fnd, i}
							<FindingCard
								finding={fnd}
								rank={i + 1}
								active={highlight != null && fnd.window != null && highlight[0] === fnd.window[0] && highlight[1] === fnd.window[1]}
								onfocus={(w) => (highlight = w)}
							/>
						{/each}
						{#if notes.more.length}
							<button class="text-sm text-accent hover:underline" onclick={() => (showMore = !showMore)}>
								{showMore ? 'Hide' : 'Show'} {notes.more.length} more finding{notes.more.length === 1 ? '' : 's'}
							</button>
							{#if showMore}
								{#each notes.more as fnd}
									<FindingCard finding={fnd} onfocus={(w) => (highlight = w)} />
								{/each}
							{/if}
						{/if}
					</div>

					<div class="space-y-3">
						{#if notes.positives.length}
							<h2 class="text-base font-semibold">What went well</h2>
							{#each notes.positives as fnd}
								<FindingCard finding={fnd} />
							{/each}
						{/if}

						<div class="card p-4">
							<div class="mb-2 flex items-center gap-2">
								<Icon name="sparkles" class="size-4 text-accent" />
								<h2 class="text-sm font-semibold">Commander debrief</h2>
								<span class="chip ml-auto bg-raised text-faint">local LLM</span>
							</div>
							{#if data.debrief}
								<div class="text-sm leading-relaxed whitespace-pre-line text-muted">{data.debrief}</div>
								{#if data.debriefUnverified.length}
									<p class="mt-2 rounded-md bg-major/10 p-2 text-xs text-major">
										Contains numbers not found in the analysis ({data.debriefUnverified.join(', ')}). Trust the
										findings above instead.
									</p>
								{/if}
								<button class="btn mt-3" onclick={writeDebrief} disabled={debriefBusy || !live.llm?.enabled}>
									<Icon name="refresh" class="size-4" /> Rewrite
								</button>
							{:else if live.llm?.enabled && live.llm.modelInstalled && live.llm.serverInstalled}
								<p class="text-sm text-muted">Turn the findings into a short squad debrief you can paste in chat.</p>
								<button class="btn btn-primary mt-3" onclick={writeDebrief} disabled={debriefBusy || live.llm.busy}>
									{#if debriefBusy}<span class="size-3 animate-spin rounded-full border-2 border-white border-t-transparent"></span> Writing…{:else}Write debrief{/if}
								</button>
							{:else}
								<p class="text-sm text-muted">
									Optional: a small local model can turn these findings into a paste-ready debrief.
									<a class="text-accent hover:underline" href="/settings#llm">Set it up in Settings</a>.
								</p>
							{/if}
						</div>

						<div class="card p-4">
							<h2 class="section-title mb-3">Enemy composition</h2>
							<div class="flex flex-wrap gap-1.5">
								{#each stats.enemies.professions as p}
									<span class="chip bg-raised text-muted">
										<span class="size-2 rounded-full" style="background:{profColor(p.profession)}"></span>
										{p.profession} <b class="text-text">{p.count}</b>
									</span>
								{/each}
							</div>
						</div>
					</div>
				</div>
			{:else}
				<div class="mb-3 flex flex-wrap items-center gap-3">
					{#if tab === 'boons'}
						<div class="flex rounded-lg border border-line-2 p-0.5">
							{#each boonGroups as g}
								<button
									class="rounded-md px-2.5 py-1 text-xs {boonGroup === g ? 'bg-raised text-text' : 'text-muted hover:text-text'}"
									onclick={() => (boonGroup = g)}>{g}</button
								>
							{/each}
						</div>
					{/if}
					<div class="ml-auto flex items-center gap-3">
						<label class="flex items-center gap-2 text-xs text-muted">
							<input type="checkbox" class="accent-accent" bind:checked={hideAbsent} /> Hide players not in the fight
						</label>
						<div class="flex rounded-lg border border-line-2 p-0.5">
							{#each ['player', 'party'] as m}
								<button
									class="rounded-md px-2.5 py-1 text-xs capitalize {mode === m ? 'bg-raised text-text' : 'text-muted hover:text-text'}"
									onclick={() => (mode = m as 'player' | 'party')}>{m === 'player' ? 'Players' : 'Parties'}</button
								>
							{/each}
						</div>
					</div>
				</div>

				{#if tab === 'overview'}
					<StatTable columns={overviewCols} players={stats.players} parties={stats.parties} squad={stats.squad} {mode} {hideAbsent} />
				{:else if tab === 'boons'}
					<StatTable columns={cols('boons', boonGroup)} players={stats.players} parties={stats.parties} squad={stats.squad} {mode} {hideAbsent} />
					<p class="mt-2 text-xs text-faint">
						Uptime: % of time the player had the boon (stability and might also as average stacks). Generation:
						what this player gave each target in the group - % of time, and for stability/might also the average
						stacks. Party and squad rows add up their members.
					</p>
				{:else if tab === 'positioning'}
					<StatTable columns={[...cols('positioning'), overviewCols.find((c) => c.key === 'fight_dist_tag')!]} players={stats.players} parties={stats.parties} squad={stats.squad} {mode} {hideAbsent} />
					<h2 class="section-title mt-6 mb-2">Downs during the fight</h2>
					<div class="card overflow-auto">
						<table class="w-full text-sm">
							<thead>
								<tr class="border-b border-line text-left text-xs text-muted">
									<th class="px-4 py-2 font-medium">Time</th>
									<th class="px-3 py-2 font-medium">Player</th>
									<th class="px-3 py-2 text-right font-medium">Party</th>
									<th class="px-3 py-2 text-right font-medium">Dist. tag</th>
									<th class="px-3 py-2 text-right font-medium">Dist. stack</th>
									<th class="px-3 py-2 text-right font-medium">Stab</th>
									<th class="px-3 py-2 text-right font-medium">Boons</th>
									<th class="px-3 py-2 text-right font-medium">Conditions</th>
									<th class="px-3 py-2 font-medium">Outcome</th>
								</tr>
							</thead>
							<tbody>
								{#each stats.timeline.squadDowns as d}
									<tr class="border-b border-line/50 last:border-0">
										<td class="tabular px-4 py-1.5">{duration(d.t)}</td>
										<td class="px-3 py-1.5">
											<span class="mr-1.5 inline-block size-2 rounded-full" style="background:{profColor(d.profession)}"></span>{d.player}
										</td>
										<td class="tabular px-3 py-1.5 text-right text-muted">{d.group}</td>
										<td class="tabular px-3 py-1.5 text-right {(d.dist_tag ?? 0) > 1000 ? 'text-major' : 'text-muted'}">{fmtValue(d.dist_tag, 'dist')}</td>
										<td class="tabular px-3 py-1.5 text-right {(d.dist_stack ?? 0) > 800 ? 'text-major' : 'text-muted'}">{fmtValue(d.dist_stack, 'dist')}</td>
										<td class="tabular px-3 py-1.5 text-right {d.stab > 0 ? 'text-muted' : 'text-loss'}">{d.stab}</td>
										<td class="tabular px-3 py-1.5 text-right text-muted">{d.boons}</td>
										<td class="tabular px-3 py-1.5 text-right {d.conditions >= 5 ? 'text-major' : 'text-muted'}">{d.conditions}</td>
										<td class="px-3 py-1.5">{#if d.died}<span class="text-loss">Died</span>{:else}<span class="text-win">Rallied / ressed</span>{/if}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{:else}
					<StatTable columns={cols(tab)} players={stats.players} parties={stats.parties} squad={stats.squad} {mode} {hideAbsent} />
				{/if}
			{/if}
		{/if}
	{/if}
</div>
