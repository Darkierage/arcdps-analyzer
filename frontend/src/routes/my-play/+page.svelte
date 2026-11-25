<script lang="ts">
	import { onMount } from 'svelte';
	import { replaceState } from '$app/navigation';
	import { page } from '$app/state';
	import { api, type PlayerInfo, type PlayerReview as Review } from '#lib/api.ts';
	import { live, toasts } from '#lib/live.svelte.ts';
	import { dateLabel, duration, profColor } from '#lib/format.ts';
	import { myPlaySearch, parseScope, SCOPES, scopeQuery, type ScopeKey } from '#lib/myplay.ts';
	import PlayerReview from '#lib/components/PlayerReview.svelte';

	let players = $state<PlayerInfo[]>([]);
	let player = $state<string | null>(null);
	let scope = $state<ScopeKey>('last5');
	let spec = $state<string | null>(null);
	let review = $state<Review | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let ready = $state(false);

	onMount(async () => {
		// Player, scope and spec live in the URL (?player=, ?scope=, ?spec=). Read from the
		// address bar: after Back, `page.url` can still hold the URL first opened.
		const q = new URL(window.location.href).searchParams;
		scope = parseScope(q.get('scope'));
		spec = q.get('spec');
		try {
			const r = await api.players();
			players = r.players;
			player = q.get('player') ?? r.default;
		} catch (e) {
			toasts.error(e);
		}
		ready = true;
		loading = false;
	});

	function writeUrl() {
		const u = new URL(window.location.href);
		u.search = myPlaySearch(player, scope, spec);
		replaceState(u, page.state);
	}

	$effect(() => {
		if (!ready || !player) return;
		const acc = player;
		const q = scopeQuery(scope, spec);
		let stale = false;
		loading = true;
		error = null;
		api.review(acc, q)
			.then((r) => !stale && (review = r))
			.catch((e) => !stale && ((review = null), (error = e instanceof Error ? e.message : String(e))))
			.finally(() => !stale && (loading = false));
		return () => {
			stale = true;
		};
	});

	// A new fight may change the review: reload quietly once things settle.
	onMount(() => {
		let t: ReturnType<typeof setTimeout> | null = null;
		const off = live.on((e) => {
			if (e.type !== 'fight' || e.fight.status !== 'done' || !player) return;
			if (t) clearTimeout(t);
			t = setTimeout(async () => {
				try {
					review = await api.review(player!, scopeQuery(scope, spec));
				} catch {
					/* keep the old view */
				}
			}, 1500);
		});
		return () => {
			if (t) clearTimeout(t);
			off();
		};
	});

	function setPlayer(acc: string) {
		player = acc;
		spec = null;
		writeUrl();
	}
	function setScope(s: ScopeKey) {
		scope = s;
		writeUrl();
	}
	function setSpec(s: string | null) {
		spec = s;
		writeUrl();
	}

	const info = $derived(players.find((p) => p.account === player) ?? null);
	const specs = $derived(review?.allSpecs ?? info?.professions ?? []);
</script>

<div class="page">
	<div class="mb-5 flex flex-wrap items-end gap-4">
		<div>
			<h1 class="text-xl font-semibold">My play</h1>
			<p class="mt-0.5 text-sm text-muted">
				What to work on, from your own logs: your survival next to the rest of the squad's, your output next to
				players with your spec and job, in the same fights.
			</p>
		</div>
	</div>

	{#if ready && !players.length}
		<div class="card px-6 py-14 text-center text-sm text-muted">
			No analyzed fights yet. Record a raid or import logs; every squad member in them can be reviewed here.
		</div>
	{:else}
		<div class="card mb-5 flex flex-wrap items-center gap-3 p-3">
			<select class="input !w-auto !py-1 text-sm" value={player ?? ''} onchange={(e) => setPlayer(e.currentTarget.value)} aria-label="Player">
				{#each players as p (p.account)}
					<option value={p.account}>{p.names[0] ?? p.account} ({p.account}) · {p.fights} fight{p.fights === 1 ? "" : "s"}{p.povFights ? ' · your logs' : ''}</option>
				{/each}
			</select>
			<div class="flex gap-1">
				{#each SCOPES as s (s.key)}
					<button class="chip {scope === s.key ? 'bg-accent/20 text-accent' : 'bg-raised text-muted hover:text-text'}" onclick={() => setScope(s.key)}>
						{s.label}
					</button>
				{/each}
			</div>
			{#if specs.length > 1}
				<div class="flex flex-wrap gap-1">
					<button class="chip {spec == null ? 'bg-accent/20 text-accent' : 'bg-raised text-muted hover:text-text'}" onclick={() => setSpec(null)}>All specs</button>
					{#each specs as sp (sp)}
						<button class="chip {spec === sp ? 'bg-accent/20 text-accent' : 'bg-raised text-muted hover:text-text'}" onclick={() => setSpec(sp)}>
							<span class="mr-1 inline-block size-2 rounded-full" style="background:{profColor(sp)}"></span>{sp}
						</button>
					{/each}
				</div>
			{/if}
		</div>

		{#if review && review.account === player}
			{@const sc = review.scope}
			<p class="mb-4 text-sm text-muted">
				<span class="font-medium text-text">{review.name}</span>:
				{sc.fights} fight{sc.fights === 1 ? '' : 's'} in {sc.sessions} session{sc.sessions === 1 ? '' : 's'}
				{#if sc.from}({dateLabel(sc.from)}{sc.to && dateLabel(sc.to) !== dateLabel(sc.from) ? ` – ${dateLabel(sc.to)}` : ''}){/if},
				{duration(sc.activeS)} in fights{#if sc.specs.length}: {sc.specs.map((x) => `${x.spec} ${x.fights}`).join(', ')}{/if}.
				{#if sc.commanderFights}<span class="text-faint">{sc.commanderFights} led (counted for survival and food only).</span>{/if}
			</p>
			<div class:opacity-60={loading}>
				<PlayerReview {review} />
			</div>
		{:else if error}
			<div class="card p-5 text-sm text-muted">{error}</div>
		{:else}
			<div class="card h-40 animate-pulse"></div>
		{/if}
	{/if}
</div>
