<script lang="ts">
	import type { PlayerReview } from '#lib/api.ts';
	import { fightLink } from '#lib/myplay.ts';
	import AdviceCard from './AdviceCard.svelte';
	import DownList from './DownList.svelte';
	import MyNumbers from './MyNumbers.svelte';

	/** A session's or several sessions' review: work on, keep doing, your downs, your numbers. */
	let { review }: { review: PlayerReview } = $props();
	let showMore = $state(false);
	let showGates = $state(false);
	const adv = $derived(review.advice);
	const session = $derived(review.scope.kind === 'session');
	const pct = (n: number, of: number) => (of ? `${Math.round((100 * n) / of)}%` : '–');
</script>

{#if review.scope.fights === 0}
	<div class="card px-6 py-12 text-center text-sm text-muted">No analyzed fights for this player in this range.</div>
{:else if adv}
	<div class="grid gap-5 lg:grid-cols-3">
		<div class="space-y-3 lg:col-span-2">
			<h2 class="text-base font-semibold">Work on</h2>
			{#if adv.nothing}
				<div class="card p-5">
					<h3 class="font-semibold">{adv.nothing.title}</h3>
					<p class="mt-1 text-sm text-muted">{adv.nothing.cause}</p>
					{#if session}
						<p class="mt-2 text-xs text-faint">One session is a small sample: a pattern needs more fights (see My play).</p>
					{/if}
				</div>
			{/if}
			{#each adv.work as a (a.key + (a.spec ?? ''))}
				<AdviceCard advice={a} player={review.account} />
			{/each}
			{#if adv.more.length}
				<button class="text-sm text-accent hover:underline" onclick={() => (showMore = !showMore)}>
					{showMore ? 'Hide' : 'Show'} {adv.more.length} more
				</button>
				{#if showMore}
					{#each adv.more as a (a.key + (a.spec ?? ''))}
						<AdviceCard advice={a} player={review.account} />
					{/each}
				{/if}
			{/if}
			{#if adv.keep.length}
				<h2 class="pt-2 text-base font-semibold">Keep doing</h2>
				{#each adv.keep as a (a.key + (a.spec ?? ''))}
					<AdviceCard advice={a} player={review.account} />
				{/each}
			{/if}
			{#if review.gates.length}
				<button class="text-xs text-faint hover:text-text" onclick={() => (showGates = !showGates)}>
					{showGates ? 'Hide' : 'Show'} what isn't judged yet ({review.gates.length})
				</button>
				{#if showGates}
					<ul class="card space-y-1 p-4 text-xs text-muted">
						{#each review.gates as g}
							<li><span class="text-text">{g.label}{g.spec ? ` · ${g.spec}` : ''}:</span> {g.need}</li>
						{/each}
					</ul>
				{/if}
			{/if}
		</div>

		<div class="space-y-5">
			<section class="card p-4">
				<h2 class="section-title mb-2">Your downs</h2>
				<p class="text-sm"><span class="tabular font-semibold">{review.downCount}</span> downs, <span class="tabular font-semibold">{review.deathCount}</span> deaths</p>
				{#if review.downCount}
					<table class="mt-2 w-full text-xs">
						<thead class="text-left text-faint">
							<tr><th class="py-1 font-medium">Of your downs</th><th class="py-1 text-right font-medium">You</th><th class="py-1 text-right font-medium" title="The rest of the squad's share in the same fights">Squad</th></tr>
						</thead>
						<tbody>
							{#each review.downSplit as x (x.key)}
								<tr class="border-t border-line">
									<td class="py-1 pr-2 text-muted">{x.label}</td>
									<td class="tabular py-1 text-right">{pct(x.you, x.of)}</td>
									<td class="tabular py-1 text-right text-muted">{x.squadExpected == null ? '–' : pct(x.squadExpected, x.of)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
					<p class="mt-1 text-[11px] text-faint">A share only means something next to the squad's: most downs come in bombs.</p>
				{/if}
				{#if review.recentDowns?.length}
					<h3 class="mt-4 mb-1 text-xs font-medium text-faint">Latest</h3>
					<DownList downs={review.recentDowns} showFight href={(d) => fightLink(d.fightId, d.key ?? review.account, d.t)} />
				{/if}
			</section>
		</div>
	</div>

	<section class="card mt-5 p-4">
		<h2 class="section-title mb-2">Your numbers</h2>
		<MyNumbers numbers={review.numbers} showTrend={review.scope.kind === 'profile'} />
		<p class="mt-2 text-[11px] text-faint">
			Per minute of your time in the fight. Peers: other players with your spec and job in the same fights.
			{#if review.scope.commanderFights}Fights you led have no distance to the tag.{/if}
		</p>
	</section>
{/if}
