<script lang="ts">
	import { page } from '$app/state';
	import { goto, replaceState } from '$app/navigation';
	import { onMount, tick, untrack } from 'svelte';
	import { api, type Column, type Occurrence, type PlayerReview as Review, type Row, type SessionDetail } from '#lib/api.ts';
	import { live, toasts } from '#lib/live.svelte.ts';
	import { compact, dateLabel, duration, fmtValue, profColor, timeOfDay } from '#lib/format.ts';
	import FightList from '#lib/components/FightList.svelte';
	import StatTable from '#lib/components/StatTable.svelte';
	import SessionTrend from '#lib/components/SessionTrend.svelte';
	import { DEFAULT_STAT, parseSessionView, rememberSession, sessionSearch } from '#lib/sessionNav.ts';
	import { statTableNote } from '#lib/sessionNotes.ts';
	import Badge, { severityBar } from '#lib/components/Badges.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import PlayerReview from '#lib/components/PlayerReview.svelte';

	const id = $derived(Number(page.params.id));
	let data = $state<SessionDetail | null>(null);
	let loading = $state(true);
	let editing = $state(false);
	let name = $state('');
	let tab = $state('summary');
	let open = $state<string | null>(null); // expanded strength / problem row
	// Stat tabs: like the fight page, plus per-minute values and a minimum time in fights.
	let mode = $state<'player' | 'party'>('player');
	let boonGroup = $state('Uptime');
	let perMin = $state(false);
	let minMinutes = $state(0);
	// Session trend: which stat, and for whom ('squad', 'party:<n>' or 'player:<account>').
	let trendKey = $state(DEFAULT_STAT);
	let trendWho = $state('squad');

	const tabs = [
		{ id: 'summary', label: 'Summary' },
		{ id: 'overview', label: 'Overview' },
		{ id: 'boons', label: 'Boons' },
		{ id: 'offense', label: 'Offense' },
		{ id: 'support', label: 'Support' },
		{ id: 'defense', label: 'Defense' },
		{ id: 'positioning', label: 'Positioning' },
		{ id: 'fights', label: 'Fights' },
		{ id: 'you', label: 'You' }
	];

	// "You" tab: one player's recap of this session. It follows the player picked for the
	// trend (?player=); without one, the "My play" account if it played here.
	let defaultAccount = $state<string | null>(null);
	onMount(() => {
		api.players().then((r) => (defaultAccount = r.default)).catch(() => {});
	});
	let youReview = $state<Review | null>(null);
	let youError = $state<string | null>(null);
	$effect(() => {
		const acc = youAccount;
		const sid = id;
		void data;
		if (tab !== 'you' || !acc) return;
		youError = null;
		let stale = false;
		api.review(acc, { session: sid })
			.then((r) => !stale && (youReview = r))
			.catch((e) => !stale && ((youReview = null), (youError = e instanceof Error ? e.message : String(e))));
		return () => {
			stale = true;
		};
	});
	const boonGroups = ['Uptime', 'Self generation', 'Group generation', 'Off-group generation', 'Squad generation'];

	const toggle = (k: string) => (open = open === k ? null : k);

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
		// Deep links: ?tab=<tab>, ?player=<account> and ?stat=<key> (the Summary's trend).
		// Read from the address bar, not `page.url`: after browser Back to this page, `page.url`
		// still holds the URL it was first opened with, not the one `syncUrl` wrote since.
		untrack(() => {
			const here = new URL(window.location.href);
			const v = parseSessionView(here.searchParams, tabs.map((x) => x.id), Object.keys(TREND_LABELS));
			tab = v.tab;
			trendWho = v.player ? `player:${v.player}` : 'squad';
			trendKey = v.stat;
			rememberSession(id, here.pathname + here.search);
		});
		load();
	});

	/** The URL in the address bar (shallow routing doesn't update `page.url`). */
	function syncUrl() {
		const u = new URL(window.location.href);
		const player = trendWho.startsWith('player:') ? trendWho.slice(7) : null;
		u.search = sessionSearch(u.searchParams, { tab, player, stat: trendKey }).toString();
		replaceState(u, page.state);
		rememberSession(id, u.pathname + u.search);
	}

	function setTab(t: string) {
		tab = t;
		syncUrl();
	}

	function setTrendWho(w: string) {
		trendWho = w;
		syncUrl();
	}

	function setTrendKey(k: string) {
		trendKey = k;
		syncUrl();
	}

	/** A player's name in a stat table: their trend on the Summary tab. */
	async function showPlayer(r: Row) {
		trendWho = `player:${r.account}`;
		setTab('summary');
		await tick();
		document.getElementById('session-trend')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
	}

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
	const boardFmt = (key: string) => agg?.columns.find((c) => c.key === key)?.fmt ?? 'num';

	// The fight page's "Dist. to tag (fight)" column (a per-fight value, not an EI column).
	const fightDistTag: Column = {
		key: 'fight_dist_tag', label: 'Dist. to tag (fight)', tab: 'positioning', agg: 'mean', fmt: 'dist',
		higherIsBetter: false, group: null, session: 'time',
		description: 'Median distance to the tag while up during each fight, weighted by time in the fight.'
	};
	const colsOf = (tabName: string, group?: string) =>
		(agg?.columns ?? []).filter((c) => c.tab === tabName && (group === undefined || c.group === group));
	const tabCols = $derived.by((): Column[] => {
		if (!agg) return [];
		if (tab === 'overview') {
			return ['active_s', 'damage', 'down_contribution', 'strips', 'cleanses', 'healing', 'up_1122', 'up_26980', 'downs', 'deaths', 'fight_dist_tag']
				.map((k) => (k === 'fight_dist_tag' ? fightDistTag : agg.columns.find((c) => c.key === k)))
				.filter(Boolean) as Column[];
		}
		if (tab === 'boons') return colsOf('boons', boonGroup);
		if (tab === 'positioning') return [...colsOf('positioning'), fightDistTag];
		return colsOf(tab);
	});
	// Per minute: counts and amounts divided by time in fights; rates (uptime, generation,
	// distances) stay as they are. Time in fights stays a total.
	const perMinCol = (c: Column) => perMin && c.session === 'sum' && c.key !== 'active_s';
	const shownCols = $derived(tabCols.map((c) => (perMinCol(c) ? { ...c, label: `${c.label}/min` } : c)));
	function view(r: Row): Row {
		if (!perMin || !r.perMin) return r;
		const { active_s: _, ...rates } = r.perMin;
		return { ...r, ...rates };
	}
	const tablePlayers = $derived((agg?.players ?? []).filter((r) => r.activeS >= minMinutes * 60).map(view));
	const tableParties = $derived((agg?.parties ?? []).map(view));
	const tableSquad = $derived(agg?.squad ? view(agg.squad) : null);
	const hiddenPlayers = $derived((agg?.players.length ?? 0) - tablePlayers.length);

	// Session trend.
	const TREND_LABELS: Record<string, string> = {
		up_1122: 'Stability uptime',
		gen_squadBuffs_1122: 'Stability given (squad)',
		strips: 'Strips',
		cleanses: 'Cleanses',
		incoming_strips: 'Boons lost',
		damage: 'Damage',
		downs: 'Downs',
		deaths: 'Deaths',
		fight_dist_tag: 'Dist. to tag'
	};
	const trendKeys = $derived(agg?.trend?.keys ?? []);
	const partyIds = $derived(Object.keys(agg?.trend?.parties ?? {}).sort((a, b) => Number(a) - Number(b)));
	const youAccount = $derived(
		(trendWho.startsWith('player:') && agg?.players.some((r) => r.account === trendWho.slice(7)) ? trendWho.slice(7) : null) ??
			(defaultAccount && agg?.players.some((r) => r.account === defaultAccount) ? defaultAccount : null) ??
			agg?.players[0]?.account ??
			null
	);
	const trendPlayers = $derived([...(agg?.players ?? [])].sort((a, b) => String(a.name).localeCompare(String(b.name))));
	// A ?player= that isn't in this session falls back to the squad.
	const who = $derived.by(() => {
		const tr = agg?.trend;
		if (tr && trendWho.startsWith('party:') && tr.parties[trendWho.slice(6)]) return trendWho;
		if (tr && trendWho.startsWith('player:') && tr.players[trendWho.slice(7)]) return trendWho;
		return 'squad';
	});
	const trendSource = $derived.by(() => {
		const tr = agg?.trend;
		if (!tr) return null;
		return who.startsWith('party:') ? tr.parties[who.slice(6)] : who.startsWith('player:') ? tr.players[who.slice(7)] : tr.squad;
	});
	const trendValues = $derived(trendSource?.[trendKey] ?? []);
	// In each fight or not: damage always has a value when they were in it.
	const trendPresent = $derived((trendSource?.damage ?? []).map((v) => v != null));
	const trendMissing = $derived(trendKey === 'fight_dist_tag' ? 'no distance (the commander, or no tag)' : 'no value');
	const trendPlayer = $derived(who.startsWith('player:') ? agg?.players.find((r) => r.account === who.slice(7)) : null);
	const trendLabel = $derived(
		`${who === 'squad' ? 'Squad' : who.startsWith('party:') ? `Party ${who.slice(6)}` : (trendPlayer?.name ?? '')}: ${TREND_LABELS[trendKey] ?? trendKey}`
	);
	const trendFmt = $derived(trendKey === 'fight_dist_tag' ? 'dist' : (agg?.columns.find((c) => c.key === trendKey)?.fmt ?? 'num'));

	function openFight(fightId: number) {
		const q = new URLSearchParams({ from: 'session' });
		if (who.startsWith('player:')) {
			q.set('tab', 'boons');
			q.set('player', who.slice(7));
		}
		goto(`/fights/${fightId}?${q}`);
	}
</script>

{#snippet occurrences(list: Occurrence[] | undefined)}
	<ul class="border-t border-line/50 bg-panel-2/40 py-1">
		{#each list ?? [] as o}
			<li>
				<a href="/fights/{o.fightId}?finding={encodeURIComponent(o.findingKey)}&from=session"
					class="group flex items-start gap-3 px-4 py-2 text-xs hover:bg-panel-2" title="Open this fight's debrief at this note">
					<span class="tabular w-16 shrink-0 pt-0.5 whitespace-nowrap text-muted">{timeOfDay(o.start)}</span>
					<span class="w-12 shrink-0">{#if o.result}<Badge result={o.result} />{/if}</span>
					<span class="min-w-0 flex-1">
						<span class="block text-faint">{o.map ?? ''}{o.mode === 'gvg' ? ' · GvG' : ''}</span>
						<span class="block text-text">{o.short}</span>
					</span>
					<Icon name="chevron" class="mt-0.5 size-3.5 shrink-0 text-faint group-hover:text-accent" />
				</a>
			</li>
		{:else}
			<li class="px-4 py-2 text-xs text-faint">No fights.</li>
		{/each}
	</ul>
{/snippet}

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

		<div class="mb-4 flex flex-wrap gap-1 border-b border-line">
			{#each tabs as t}
				<button
					class="-mb-px border-b-2 px-3.5 py-2 text-sm {tab === t.id ? 'border-accent font-medium text-text' : 'border-transparent text-muted hover:text-text'}"
					onclick={() => setTab(t.id)}>{t.label}</button
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
							{@const k = `issue:${r.key}`}
							<div>
								<button class="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-panel-2" aria-expanded={open === k}
									onclick={() => toggle(k)} title="Show the fights with this problem">
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
									<Icon name="chevron" class="size-4 shrink-0 text-faint transition {open === k ? 'rotate-90' : ''}" />
								</button>
								{#if open === k}{@render occurrences(r.occurrences)}{/if}
							</div>
						{/each}
					</div>
					{#if agg.positives.length}
						<h2 class="pt-2 text-base font-semibold">Strengths</h2>
						<div class="card divide-y divide-line">
							{#each agg.positives as r}
								{@const k = `pos:${r.key}`}
								<div>
									<button class="flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm hover:bg-panel-2" aria-expanded={open === k}
										onclick={() => toggle(k)} title="Show the fights that earned this">
										<Icon name="check" class="size-4 text-win" />
										<span class="flex-1">{r.title}</span>
										<span class="tabular text-xs text-faint">{r.count} fight{r.count === 1 ? '' : 's'}</span>
										<Icon name="chevron" class="size-4 shrink-0 text-faint transition {open === k ? 'rotate-90' : ''}" />
									</button>
									{#if open === k}{@render occurrences(r.occurrences)}{/if}
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
										<span class="ml-auto text-[11px] text-faint" title={board.rate ? `Weighted by time in each fight; only players in at least a quarter of the session's fight time` : ''}>{board.rate ? 'time-weighted' : 'total · per fight'}</span>
									</div>
									<ol class="space-y-1.5">
										{#each board.rows.slice(0, 5) as r, i}
											<li class="flex items-center gap-2 text-sm">
												<span class="tabular w-4 text-xs text-faint">{i + 1}</span>
												<span class="size-2 shrink-0 rounded-full" style="background:{profColor(r.profession.split(', ')[0])}"></span>
												<span class="min-w-0 flex-1 truncate" title={r.account}>{r.name}</span>
												<span class="tabular font-medium">{fmtValue(r.total, boardFmt(key))}</span>
												{#if r.perFight != null}
													<span class="tabular w-14 text-right text-xs text-faint">{fmtValue(r.perFight, boardFmt(key))}</span>
												{/if}
											</li>
										{/each}
									</ol>
								</div>
							{/if}
						{/each}
					</div>
				</div>
			</div>
			<div class="card mt-5 scroll-mt-4 p-4" id="session-trend">
				<div class="mb-1 flex flex-wrap items-center gap-3">
					<h2 class="section-title">Session trend</h2>
					<div class="ml-auto flex flex-wrap items-center gap-2">
						<select class="input py-1 text-xs" value={trendKey} onchange={(e) => setTrendKey(e.currentTarget.value)} aria-label="Stat">
							{#each trendKeys as k}<option value={k}>{TREND_LABELS[k] ?? k}</option>{/each}
						</select>
						<select class="input py-1 text-xs" value={who} onchange={(e) => setTrendWho(e.currentTarget.value)} aria-label="Squad, party or player">
							<option value="squad">Squad</option>
							{#if partyIds.length}
								<optgroup label="Parties">
									{#each partyIds as g}<option value="party:{g}">Party {g}</option>{/each}
								</optgroup>
							{/if}
							<optgroup label="Players">
								{#each trendPlayers as r}<option value="player:{r.account}">{r.name} ({r.fights})</option>{/each}
							</optgroup>
						</select>
					</div>
				</div>
				<SessionTrend
					fights={agg.fights}
					values={trendValues}
					reference={who.startsWith('player:') ? (agg.trend.playerAvg[trendKey] ?? null) : null}
					referenceLabel="Average player"
					label={trendLabel}
					fmt={trendFmt}
					present={trendPresent}
					missingLabel={trendMissing}
					onfight={openFight}
				/>
				<p class="mt-1 text-xs text-faint">
					One point per fight, coloured by result; gaps are fights {who.startsWith('player:') ? 'this player was not in' : 'without them'}{trendKey === 'fight_dist_tag' ? ', or without a distance to tag (the commander, or a fight without a tag)' : ''}.
					{#if who.startsWith('player:')}The dashed line is the squad's average player.{/if}
					Click a fight to open it{who.startsWith('player:') ? ' at this player\'s boons' : ''}. Pick a player here or click a name in a stat table.
				</p>
			</div>
		{:else if tab === 'fights'}
			<FightList fights={data.fights} showDate={false} />
		{:else if tab === 'you'}
			<div class="mb-4 flex flex-wrap items-center gap-3">
				<label class="flex items-center gap-2 text-sm text-muted">
					Player
					<select class="input !w-auto !py-1 text-sm" value={youAccount ?? ''} onchange={(e) => setTrendWho(`player:${e.currentTarget.value}`)}>
						{#each trendPlayers as r (r.account)}<option value={r.account}>{r.name} ({r.fights})</option>{/each}
					</select>
				</label>
				{#if youAccount}
					<a class="ml-auto text-xs text-accent hover:underline" href="/my-play?player={encodeURIComponent(youAccount)}">More sessions in My play →</a>
				{/if}
			</div>
			{#if youError}
				<div class="card p-5 text-sm text-muted">{youError}</div>
			{:else if youReview && youReview.account === youAccount}
				<PlayerReview review={youReview} />
			{:else}
				<div class="card h-40 animate-pulse"></div>
			{/if}
		{:else}
			<div class="mb-3 flex flex-wrap items-center gap-3">
				{#if tab === 'boons'}
					<div class="flex flex-wrap rounded-lg border border-line-2 p-0.5">
						{#each boonGroups as g}
							<button
								class="rounded-md px-2.5 py-1 text-xs {boonGroup === g ? 'bg-raised text-text' : 'text-muted hover:text-text'}"
								onclick={() => (boonGroup = g)}>{g}</button
							>
						{/each}
					</div>
				{/if}
				<div class="ml-auto flex flex-wrap items-center gap-3">
					<label class="flex items-center gap-2 text-xs text-muted" title="Hide players who spent less time in this session's fights">
						Min. time in fights
						<select class="input py-1 text-xs" bind:value={minMinutes}>
							{#each [0, 5, 15, 30] as m}<option value={m}>{m ? `${m} min` : 'Any'}</option>{/each}
						</select>
					</label>
					<div class="flex rounded-lg border border-line-2 p-0.5" title="Counts and amounts per minute in fights (uptime and other rates are unchanged)">
						{#each [[false, 'Total'], [true, 'Per minute']] as [v, label]}
							<button
								class="rounded-md px-2.5 py-1 text-xs {perMin === v ? 'bg-raised text-text' : 'text-muted hover:text-text'}"
								onclick={() => (perMin = v as boolean)}>{label}</button
							>
						{/each}
					</div>
					<div class="flex rounded-lg border border-line-2 p-0.5">
						{#each ['player', 'party'] as m}
							<button
								class="rounded-md px-2.5 py-1 text-xs {mode === m ? 'bg-raised text-text' : 'text-muted hover:text-text'}"
								onclick={() => (mode = m as 'player' | 'party')}>{m === 'player' ? 'Players' : 'Parties'}</button
							>
						{/each}
					</div>
				</div>
			</div>
			<StatTable
				columns={shownCols}
				players={tablePlayers}
				parties={tableParties}
				squad={tableSquad}
				{mode}
				hideAbsent={false}
				extraLead={{ key: 'fights', label: 'Fights' }}
				onrow={showPlayer}
				rowTitle="Show this player's stats fight by fight"
			/>
			<p class="mt-2 text-xs text-faint">
				{statTableNote(mode, perMin, hiddenPlayers)}
			</p>
		{/if}
	{/if}
</div>
