<script lang="ts">
	import { page } from '$app/state';
	import { goto, pushState, replaceState } from '$app/navigation';
	import { onMount, tick, untrack } from 'svelte';
	import { api, type Column, type FightDetail, type FindingFocus, type PlayerSeries, type Row } from '#lib/api.ts';
	import { live, toasts } from '#lib/live.svelte.ts';
	import { compact, dateLabel, duration, fmtValue, profColor, timeOfDay } from '#lib/format.ts';
	import Badge from '#lib/components/Badges.svelte';
	import FindingCard from '#lib/components/FindingCard.svelte';
	import FightTimeline from '#lib/components/FightTimeline.svelte';
	import BoonTimeline from '#lib/components/BoonTimeline.svelte';
	import PlayerBoonChart from '#lib/components/PlayerBoonChart.svelte';
	import PlayerTimelineChart from '#lib/components/PlayerTimelineChart.svelte';
	import { findSeriesRow, seriesKey } from '#lib/players.ts';
	import { sessionBackHref } from '#lib/sessionNav.ts';
	import StatTable from '#lib/components/StatTable.svelte';
	import Icon from '#lib/components/Icon.svelte';

	const id = $derived(Number(page.params.id));
	let data = $state<FightDetail | null>(null);
	let loading = $state(true);
	let tab = $state('debrief');
	let highlight = $state<[number, number] | null>(null);
	// Timeline party: 'squad', a party's group number, 'player:<key>' (that squad row's own
	// charts; the key is its `series_key`, or an account from a session link), or 'all'
	// (stability per party; Debrief only).
	let party = $state('squad');
	let mode = $state<'player' | 'party'>('player');
	let hideAbsent = $state(true);
	let boonGroup = $state('Uptime');
	let showMore = $state(false);
	let debriefBusy = $state(false);
	// Deep links: ?tab=<tab>, ?finding=<key> (from a session strength/problem), ?stat=<column>.
	let focusFinding = $state<string | null>(null);
	let focusStat = $state<FindingFocus | null>(null);
	let fromSession = $state(false);
	let pendingFinding: string | null = null;

	async function load() {
		try {
			data = await api.fight(id);
			const g = focusStat?.tab === 'boons' && data.stats?.columns.find((c: Column) => c.key === focusStat?.column)?.group;
			if (g) boonGroup = g;
			if (pendingFinding) {
				const key = pendingFinding;
				pendingFinding = null;
				showFinding(key);
			}
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
		untrack(() => {
			const q = page.url.searchParams;
			const t = q.get('tab');
			const stat = q.get('stat');
			pendingFinding = q.get('finding');
			fromSession = q.get('from') === 'session';
			party = partyFromUrl(q);
			focusFinding = null;
			showMore = false;
			tab = pendingFinding ? 'debrief' : tabs.some((x) => x.id === t) ? t! : 'debrief';
			focusStat = stat && tab !== 'debrief' ? { tab, column: stat, sort: q.get('sort') === 'asc' ? 'asc' : 'desc' } : null;
		});
		load();
	});

	/** Open the debrief at one finding: expand "more" if needed, highlight and scroll to it. */
	async function showFinding(key: string) {
		const n = data?.notes;
		const f = n && [...n.issues, ...n.more, ...n.positives].find((x) => x.key === key);
		if (!n || !f) {
			if (n) toasts.push('That note is no longer part of this fight\'s analysis.');
			return;
		}
		if (n.more.some((x) => x.key === key)) showMore = true;
		focusFinding = key;
		if (f.window) highlight = f.window;
		await tick();
		document.getElementById(`finding-${key}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
	}

	/** Switch tab (optionally focused on one stat column) and keep the URL in sync. With `push`
	 * the switch gets its own history entry, so the browser's Back returns to the old tab. */
	function setTab(t: string, focus: FindingFocus | null = null, push = false) {
		tab = t;
		cameFromTimeline = false;
		focusStat = focus;
		if (focus && t === 'boons') {
			const g = stats?.columns.find((c: Column) => c.key === focus.column)?.group;
			if (g) boonGroup = g;
		}
		const u = addressUrl();
		withParty(u);
		for (const k of ['tab', 'stat', 'sort', 'finding']) u.searchParams.delete(k);
		if (t !== 'debrief') u.searchParams.set('tab', t);
		if (focus) {
			u.searchParams.set('stat', focus.column);
			if (focus.sort === 'asc') u.searchParams.set('sort', 'asc');
		}
		if (push) pushState(u, page.state);
		else replaceState(u, page.state);
		if (focus) window.scrollTo({ top: 0, behavior: 'smooth' });
	}

	/** The URL in the address bar. pushState/replaceState (shallow routing) don't update
	 * `page.url`, which keeps the last real navigation's URL. */
	function addressUrl(): URL {
		return new URL(window.location.href);
	}

	// Back/forward between this page's own entries (All boons → pushes one): follow the address
	// bar's tab and party. A ?finding= link always shows the Debrief.
	onMount(() => {
		const follow = () => {
			cameFromTimeline = false;
			const q = addressUrl().searchParams;
			const t = q.get('finding') ? 'debrief' : (q.get('tab') ?? 'debrief');
			if (tabs.some((x) => x.id === t)) tab = t;
			party = partyFromUrl(q);
		};
		window.addEventListener('popstate', follow);
		return () => window.removeEventListener('popstate', follow);
	});

	/** Debrief timeline -> Boons tab, and back to the timeline where the reader was. */
	let cameFromTimeline = false; // the history entry before this one is the Debrief timeline
	async function openBoons() {
		setTab('boons', null, true);
		cameFromTimeline = true;
		await tick();
		document.getElementById('boons-over-time')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
	}
	async function backToTimeline() {
		if (cameFromTimeline) {
			// Go back through history (no duplicate Debrief entry), keeping the party picked here.
			const keep = party;
			const back = new Promise((r) => window.addEventListener('popstate', r, { once: true }));
			history.back();
			await back;
			if (party !== keep) setParty(keep);
		} else {
			setTab('debrief');
		}
		await tick();
		document.getElementById('fight-timeline')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
	}

	/** ?player=<account> picks that player's charts, ?party=<n> a party. */
	function partyFromUrl(q: { get(k: string): string | null }): string {
		const player = q.get('player');
		return player ? `player:${player}` : (q.get('party') ?? 'squad');
	}

	/** Put the current party / player in a URL (?party=2, ?player=<account>). */
	function withParty(u: URL): URL {
		u.searchParams.delete('party');
		u.searchParams.delete('player');
		if (party.startsWith('player:')) u.searchParams.set('player', party.slice(7));
		else if (party !== 'squad') u.searchParams.set('party', party);
		return u;
	}

	/** Pick the timeline party or player and keep it in the URL, like the tab. */
	function setParty(p: string) {
		party = p;
		replaceState(withParty(addressUrl()), page.state);
	}

	/** A player's name in a stat table: their boons over time. One URL write: replaceState is
	 * async, so a second write right after the first would start from the old address. */
	async function showPlayer(r: Row) {
		party = `player:${seriesKey(r)}`;
		setTab('boons');
		await tick();
		document.getElementById('boons-over-time')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
	}

	// Back to the session as it was left (tab, picked player), when there is one to go back to.
	const backHref = $derived(fromSession && data?.fight.session_id ? sessionBackHref(data.fight.session_id) : '/');

	const s = $derived(data?.fight.summary ?? data?.stats?.summary ?? null);
	const stats = $derived(data?.stats ?? null);
	const partyIds = $derived(Object.keys(stats?.timeline.parties ?? {}).sort((a, b) => Number(a) - Number(b)));
	// Players to pick for their own charts: by party, then name.
	const pickPlayers = $derived(
		[...(stats?.players ?? [])].sort((a, b) => a.group - b.group || String(a.name).localeCompare(String(b.name)))
	);
	// A ?party= / ?player= this fight doesn't have falls back to the squad; an account (from a
	// session link) picks that player's main row. The Boons tab chart has no "all parties" view.
	const pickedPlayer = $derived(party.startsWith('player:') ? findSeriesRow(pickPlayers, party.slice(7)) : null);
	const debriefParty = $derived(
		party === 'all' || partyIds.includes(party) ? party : pickedPlayer ? `player:${seriesKey(pickedPlayer)}` : 'squad'
	);
	const boonParty = $derived(debriefParty === 'all' ? 'squad' : debriefParty);
	const playerAcc = $derived(pickedPlayer ? seriesKey(pickedPlayer) : null);

	// The picked player's own series, fetched one player at a time (and again after a re-analysis).
	let playerSeries = $state<PlayerSeries | null>(null);
	let playerError = $state<string | null>(null);
	$effect(() => {
		const acc = playerAcc;
		const fid = id;
		void data?.stats;
		playerSeries = null;
		playerError = null;
		if (!acc) return;
		let stale = false;
		api.playerTimeline(fid, acc)
			.then((r) => !stale && (playerSeries = r))
			.catch((e) => !stale && (playerError = e instanceof Error ? e.message : String(e)));
		return () => {
			stale = true;
		};
	});
	// Player name -> profession, for the chart tooltips' death lines.
	const professions = $derived(
		Object.fromEntries((stats?.players ?? []).map((r) => [r.name as string, r.profession as string]))
	);

	/** Chip tooltip: the party's players who took part (the ones the chart is about). */
	function partyTitle(g: string): string {
		const profs = (stats?.players ?? [])
			.filter((r) => String(r.group) === g && r.in_fight !== false)
			.map((r) => r.profession as string)
			.sort();
		return profs.length ? `${profs.length} ${profs.length === 1 ? 'player' : 'players'}: ${profs.join(', ')}` : '';
	}
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

	// GvG: kills/deaths after the call-off and downs left at it are not part of the fight.
	const gvg = $derived(data?.fight.mode === 'gvg');
	const rounds = $derived(s?.mode === 'gvg' ? (s.rounds ?? []) : []);

	async function switchMode() {
		const next = gvg ? 'zerg' : 'gvg';
		try {
			await api.setFightMode(id, next);
			toasts.push(next === 'gvg' ? 'Re-analyzing as a GvG fight…' : 'Re-analyzing as a zerg fight…');
		} catch (e) {
			toasts.error(e);
		}
	}

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
	<a href={backHref} class="mb-4 inline-flex items-center gap-1.5 text-sm text-muted hover:text-text">
		<Icon name="back" class="size-4" /> {backHref === '/' ? 'Fights' : 'Session'}
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
					{#if gvg}
						<span class="chip bg-accent/15 text-accent" title="Analyzed as GvG: downs left at the call-off and kills after it are not counted">
							GvG{#if rounds.length > 1}&nbsp;· {s?.roundWins ?? 0}–{s?.roundLosses ?? 0} in {rounds.length} rounds{/if}
						</span>
					{/if}
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
				<button class="btn" onclick={switchMode}
					title={gvg ? 'Analyze this fight as a normal zerg fight' : 'Analyze this fight as GvG: rounds end with a call-off, downs left then are not counted'}>
					<Icon name="swords" class="size-4" /> {gvg ? 'Analyze as zerg' : 'Analyze as GvG'}
				</button>
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
					{#if s.mode === 'gvg'}
						<div class="tabular mt-1.5 text-lg font-semibold">
							<span class="text-win">{(s.enemyDeaths ?? 0) - (s.enemyDeathsLate ?? 0)}</span> <span class="text-faint">/</span>
							<span class="text-loss">{(s.squadDeaths ?? 0) - (s.squadDeathsLate ?? 0)}</span>
						</div>
						<div class="text-xs text-faint" title="Downs still open when the round was called off (not counted)">
							left at call-off {s.enemyDownsLeft ?? 0} / {s.squadDownsLeft ?? 0}
						</div>
					{:else}
						<div class="tabular mt-1.5 text-lg font-semibold">
							<span class="text-win">{s.enemyDeaths}</span> <span class="text-faint">/</span> <span class="text-loss">{s.squadDeaths}</span>
						</div>
						<div class="text-xs text-faint">downs {s.enemyDowns} / {s.squadDowns}</div>
					{/if}
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

			{#if rounds.length > 1}
				<div class="mb-5 flex flex-wrap items-center gap-2 text-xs">
					<span class="section-title mr-1">Rounds</span>
					{#each rounds as r, i}
						<span class="card flex items-center gap-2 px-2.5 py-1.5">
							<span class="text-faint">#{i + 1}</span>
							<Badge result={r.result} />
							<span class="tabular text-muted" title="taken out: kills + enemy downs left / deaths + our downs left">
								{r.enemyDeaths + r.enemyLeft}–{r.squadDeaths + r.squadLeft}
							</span>
							<span class="tabular text-faint">{duration(r.calloff - r.start)}</span>
						</span>
					{/each}
				</div>
			{/if}

			<!-- Tabs -->
			<div class="mb-4 flex gap-1 border-b border-line">
				{#each tabs as t}
					<button
						class="-mb-px border-b-2 px-3.5 py-2 text-sm transition {tab === t.id
							? 'border-accent font-medium text-text'
							: 'border-transparent text-muted hover:text-text'}"
						onclick={() => setTab(t.id)}
					>
						{t.label}
					</button>
				{/each}
			</div>

			{#if tab === 'debrief'}
				<div class="card mb-5 scroll-mt-4 p-4" id="fight-timeline">
					<div class="mb-1 flex items-center gap-3">
						<h2 class="section-title">Fight timeline</h2>
						<label class="ml-auto flex items-center gap-2 text-xs text-muted">
							Show
							<select class="input !w-auto !py-1 text-xs" value={debriefParty} onchange={(e) => setParty(e.currentTarget.value)}>
								<option value="squad">Squad</option>
								{#each partyIds as g}
									<option value={g}>Party {g}</option>
								{/each}
								<option value="all">All parties: stability</option>
								<optgroup label="Players">
									{#each pickPlayers as r}
										<option value="player:{seriesKey(r)}">{r.name} · Party {r.group}{r.in_fight === false ? ' (not in fight)' : ''}</option>
									{/each}
								</optgroup>
							</select>
						</label>
						<button class="text-xs text-accent hover:underline" onclick={openBoons}>All boons →</button>
					</div>
					{#if playerAcc}
						{#if playerSeries}
							<PlayerTimelineChart series={playerSeries} timeline={stats.timeline} {highlight} />
							<p class="mt-1 text-xs text-faint">
								{pickedPlayer?.name}: health, boons and conditions; damage dealt and taken and healing + barrier per second;
								distance to the tag and to the squad's center. Orange shading: downed; red: dead.
							</p>
						{:else if playerError}
							<p class="py-6 text-sm text-muted">{playerError}</p>
						{:else}
							<div class="h-[460px] animate-pulse rounded bg-panel-2/40"></div>
						{/if}
					{:else}
						<FightTimeline timeline={stats.timeline} {highlight} party={debriefParty} {professions} />
						<p class="mt-1 text-xs text-faint">Hover a ▲ down or ✕ death marker to see who.</p>
					{/if}
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
								active={focusFinding === fnd.key || (highlight != null && fnd.window != null && highlight[0] === fnd.window[0] && highlight[1] === fnd.window[1])}
								onfocus={(w) => ((highlight = w), (focusFinding = null))}
								onstats={(f) => setTab(f.tab, f)}
							/>
						{/each}
						{#if notes.more.length}
							<button class="text-sm text-accent hover:underline" onclick={() => (showMore = !showMore)}>
								{showMore ? 'Hide' : 'Show'} {notes.more.length} more finding{notes.more.length === 1 ? '' : 's'}
							</button>
							{#if showMore}
								{#each notes.more as fnd}
									<FindingCard finding={fnd} active={focusFinding === fnd.key} onfocus={(w) => ((highlight = w), (focusFinding = null))}
										onstats={(f) => setTab(f.tab, f)} />
								{/each}
							{/if}
						{/if}
					</div>

					<div class="space-y-3">
						{#if notes.positives.length}
							<h2 class="text-base font-semibold">What went well</h2>
							{#each notes.positives as fnd}
								<FindingCard finding={fnd} active={focusFinding === fnd.key} onstats={(f) => setTab(f.tab, f)} />
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
				{#if tab === 'boons'}
					<div class="card mb-5 scroll-mt-4 p-4" id="boons-over-time">
						<div class="mb-1 flex flex-wrap items-center gap-3">
							<h2 class="section-title">Boons over time</h2>
							<button class="text-xs text-accent hover:underline" onclick={backToTimeline}>← Fight timeline</button>
							<div class="ml-auto flex flex-wrap rounded-lg border border-line-2 p-0.5">
								{#each ['squad', ...partyIds] as g}
									<button
										class="rounded-md px-2.5 py-1 text-xs {boonParty === g ? 'bg-raised text-text' : 'text-muted hover:text-text'}"
										title={g === 'squad' ? '' : partyTitle(g)}
										onclick={() => setParty(g)}>{g === 'squad' ? 'Squad' : `Party ${g}`}</button
									>
								{/each}
								<select
									class="rounded-md border-0 bg-transparent px-2 py-1 text-xs {playerAcc ? 'bg-raised text-text' : 'text-muted hover:text-text'}"
									value={playerAcc ? boonParty : ''}
									onchange={(e) => setParty(e.currentTarget.value || 'squad')}
									aria-label="One player's boons"
								>
									<option value="">Player…</option>
									{#each pickPlayers as r}
										<option value="player:{seriesKey(r)}">{r.name} · Party {r.group}</option>
									{/each}
								</select>
							</div>
						</div>
						{#if playerAcc}
							{#if playerSeries}
								<PlayerBoonChart series={playerSeries} timeline={stats.timeline} />
								<p class="mt-1 text-xs text-faint">
									{pickedPlayer?.name}'s boons: each lane is filled while they had the boon; might and stability are darker
									with more stacks (hover for the count). The last two lanes show when they were downed or dead.
								</p>
							{:else if playerError}
								<p class="py-6 text-sm text-muted">{playerError}</p>
							{:else}
								<div class="h-[400px] animate-pulse rounded bg-panel-2/40"></div>
							{/if}
						{:else if stats.timeline.boons}
							<BoonTimeline timeline={stats.timeline} party={boonParty} {professions} />
							<p class="mt-1 text-xs text-faint">
								% of the {boonParty === 'squad' ? "squad's" : "party's"} players (up, not downed or dead) who had the
								boon each second; dashed lines are average stacks (right axis). Hover a ▲ / ✕ marker to see who went
								down or died. Click a boon in the legend to show or
								hide it.
							</p>
						{:else}
							<p class="py-6 text-sm text-muted">Re-analyze this fight to see boons over time.</p>
						{/if}
					</div>
				{/if}
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
					<StatTable columns={overviewCols} players={stats.players} parties={stats.parties} squad={stats.squad} {mode} {hideAbsent} focus={focusStat} onrow={showPlayer} rowTitle="Show this player's boons over time" />
				{:else if tab === 'boons'}
					<StatTable columns={cols('boons', boonGroup)} players={stats.players} parties={stats.parties} squad={stats.squad} {mode} {hideAbsent} focus={focusStat} onrow={showPlayer} rowTitle="Show this player's boons over time" />
					<p class="mt-2 text-xs text-faint">
						Uptime: % of time the player had the boon (stability and might also as average stacks). Generation:
						what this player gave each target in the group - % of time, and for stability/might also the average
						stacks. Party and squad rows add up their members.
					</p>
				{:else if tab === 'positioning'}
					<StatTable columns={[...cols('positioning'), overviewCols.find((c) => c.key === 'fight_dist_tag')!]} players={stats.players} parties={stats.parties} squad={stats.squad} {mode} {hideAbsent} focus={focusStat} onrow={showPlayer} rowTitle="Show this player's boons over time" />
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
					<StatTable columns={cols(tab)} players={stats.players} parties={stats.parties} squad={stats.squad} {mode} {hideAbsent} focus={focusStat} onrow={showPlayer} rowTitle="Show this player's boons over time" />
				{/if}
			{/if}
		{/if}
	{/if}
</div>
