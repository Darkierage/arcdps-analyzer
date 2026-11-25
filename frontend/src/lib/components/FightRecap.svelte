<script lang="ts">
	import type { PlayerDown, PlayerReview, SkillRow } from '#lib/api.ts';
	import { compact, duration } from '#lib/format.ts';
	import { JOB_LABEL } from '#lib/myplay.ts';
	import DownList from './DownList.svelte';
	import MyNumbers from './MyNumbers.svelte';

	/** One player in one fight: each down with its hint, the numbers next to the peers here,
	 * what hit them and their top skills. One fight never claims a habit. */
	let { review, onpick }: { review: PlayerReview; onpick: (d: PlayerDown) => void } = $props();
	const f = $derived(review.fight!);
	const pct = (x: number | undefined) => (x == null ? '–' : `${Math.round(x * 100)}%`);
</script>

{#snippet skills(title: string, rows: SkillRow[] | null, dealt: boolean)}
	<section class="card p-4">
		<h2 class="section-title mb-2">{title}</h2>
		{#if rows?.length}
			<table class="w-full text-xs">
				<thead class="text-left text-faint">
					<tr>
						<th class="py-1 font-medium">Skill</th>
						<th class="py-1 text-right font-medium">Damage</th>
						<th class="py-1 text-right font-medium">Share</th>
						<th class="py-1 text-right font-medium">Hits</th>
						{#if dealt}<th class="py-1 text-right font-medium" title="Hits that connected (not blocked, evaded, missed or invulned)">Landed</th>{/if}
					</tr>
				</thead>
				<tbody>
					{#each rows as r}
						<tr class="border-t border-line">
							<td class="py-1 pr-2">{r.skill}</td>
							<td class="tabular py-1 text-right">{compact(r.damage)}</td>
							<td class="tabular py-1 text-right text-muted">{pct(r.share)}</td>
							<td class="tabular py-1 text-right text-muted">{r.hits}</td>
							{#if dealt}<td class="tabular py-1 text-right text-muted" title="{r.blocked ?? 0} blocked, {r.evaded ?? 0} evaded, {r.missed ?? 0} missed">{pct(r.connected)}</td>{/if}
						</tr>
					{/each}
				</tbody>
			</table>
		{:else}
			<p class="text-xs text-faint">Not in this log for this player.</p>
		{/if}
	</section>
{/snippet}

{#if f}
	<div class="mb-4 flex flex-wrap items-center gap-2 text-sm">
		<span class="chip bg-raised text-muted">{f.specs.join(' / ')}</span>
		<span class="chip bg-raised text-muted" title="Your strongest output against the squad in this fight">
			job: {f.job ? JOB_LABEL[f.job] : 'none stood out'}
		</span>
		{#if f.commander}<span class="chip bg-accent/15 text-accent">commander</span>{/if}
		<span class="text-xs text-faint">{duration(f.activeS)} in the fight{f.deadS ? `, ${duration(f.deadS)} dead` : ''}</span>
		{#if f.food === false || f.utility === false}
			<span class="chip bg-major/15 text-major">no {f.food === false ? 'food' : ''}{f.food === false && f.utility === false ? ' or ' : ''}{f.utility === false ? 'utility' : ''}</span>
		{/if}
		<a class="ml-auto text-xs text-accent hover:underline" href="/my-play?player={encodeURIComponent(review.account)}">All fights in My play →</a>
	</div>

	<div class="grid gap-5 lg:grid-cols-3">
		<section class="card p-4 lg:col-span-2">
			<h2 class="section-title mb-1">Your downs</h2>
			{#if f.downs.length}
				<p class="mb-1 text-xs text-faint">
					{f.squad.downs_total} squad downs here, {f.squad.players_downed} players.
					{#if f.firstRank}You were the {f.firstRank}{f.firstRank === 1 ? 'st' : f.firstRank === 2 ? 'nd' : f.firstRank === 3 ? 'rd' : 'th'} player to go down.{/if}
					Click a down to see it on your charts.
				</p>
				<DownList downs={f.downs} {onpick} />
				<p class="mt-2 text-[11px] text-faint">One fight shows what happened, not a habit: My play compares many fights.</p>
			{:else}
				<p class="text-sm text-muted">You didn't go down in this fight.</p>
			{/if}
		</section>
		<section class="card p-4">
			<h2 class="section-title mb-2">You, your peers and the squad here</h2>
			<MyNumbers numbers={review.numbers} />
		</section>
	</div>
	<div class="mt-5 grid gap-5 lg:grid-cols-2">
		{@render skills('What hit you', f.taken, false)}
		{@render skills('Your top skills', f.dealt, true)}
	</div>
{/if}
