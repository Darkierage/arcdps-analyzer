<script lang="ts">
	import { onMount } from 'svelte';
	import { api, type FightRow, type SessionRow } from '#lib/api.ts';
	import { live, toasts } from '#lib/live.svelte.ts';
	import FightList from '#lib/components/FightList.svelte';
	import Icon from '#lib/components/Icon.svelte';

	let fights = $state<FightRow[]>([]);
	let sessions = $state<SessionRow[]>([]);
	let sessionId = $state<number | null>(null);
	let includeSkipped = $state(false);
	let loading = $state(true);

	async function load() {
		loading = true;
		try {
			[fights, sessions] = await Promise.all([
				api.fights({ sessionId, includeSkipped }),
				api.sessions()
			]);
		} catch (e) {
			toasts.error(e);
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		load();
		const offCancel = live.on((e) => {
			if (e.type === 'cancelled') fights = fights.filter((x) => !e.fightIds.includes(x.id));
		});
		const offFight = live.onFight((f) => {
			if (sessionId != null && f.session_id !== sessionId) return;
			if (!includeSkipped && f.status === 'skipped') {
				fights = fights.filter((x) => x.id !== f.id);
				return;
			}
			const i = fights.findIndex((x) => x.id === f.id);
			if (i >= 0) fights[i] = f;
			else fights = [f, ...fights];
		});
		return () => {
			offCancel();
			offFight();
		};
	});

	const counts = $derived({
		win: fights.filter((f) => f.result === 'win').length,
		loss: fights.filter((f) => f.result === 'loss').length,
		even: fights.filter((f) => f.result === 'even').length
	});
</script>

<div class="mx-auto max-w-7xl px-6 py-6">
	<div class="mb-5 flex flex-wrap items-end gap-4">
		<div>
			<h1 class="text-xl font-semibold">Fights</h1>
			<p class="mt-0.5 text-sm text-muted">
				{fights.length} fights ·
				<span class="text-win">{counts.win} won</span> ·
				<span class="text-loss">{counts.loss} lost</span> ·
				<span class="text-even">{counts.even} even</span>
			</p>
		</div>
		<div class="ml-auto flex items-center gap-3">
			<select class="input w-64" bind:value={sessionId} onchange={load}>
				<option value={null}>All sessions</option>
				{#each sessions as s}
					<option value={s.id}>{s.name} ({s.fights})</option>
				{/each}
			</select>
			<label class="flex items-center gap-2 text-sm text-muted">
				<input type="checkbox" class="accent-accent" bind:checked={includeSkipped} onchange={load} />
				Show skipped
			</label>
		</div>
	</div>

	{#if loading && !fights.length}
		<div class="card h-64 animate-pulse"></div>
	{:else if !fights.length}
		<div class="card flex flex-col items-center gap-3 px-6 py-16 text-center">
			<div class="grid size-12 place-items-center rounded-full bg-raised">
				<Icon name="swords" class="size-6 text-accent" />
			</div>
			<h2 class="text-base font-semibold">No fights yet</h2>
			<p class="max-w-md text-sm text-muted">
				Press <b class="text-text">Start recording</b> before your raid. Every log arcdps writes after a
				fight is picked up and analyzed automatically. You can also <b class="text-text">Import logs</b> you
				already have.
			</p>
		</div>
	{:else}
		<FightList {fights} />
	{/if}
</div>
