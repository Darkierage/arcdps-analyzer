<script lang="ts">
	import type { Advice } from '#lib/api.ts';
	import { dateLabel, timeOfDay } from '#lib/format.ts';
	import { fightLink, trendClass, trendLabel } from '#lib/myplay.ts';
	import { severityBar } from './Badges.svelte';
	import Icon from './Icon.svelte';

	/** One personal finding: what, the sample next to the squad's, the hint, trend, examples. */
	let { advice, player }: { advice: Advice; player: string } = $props();
	const positive = $derived(advice.severity === 'positive');
</script>

<article class="card relative overflow-hidden">
	<div class="absolute inset-y-0 left-0 w-1 {severityBar[advice.severity]}"></div>
	<div class="py-4 pr-4 pl-5">
		<div class="mb-1.5 flex flex-wrap items-start gap-2">
			<h3 class="min-w-0 flex-1 leading-snug font-semibold">{advice.title}</h3>
			{#if advice.trend}
				<span class="text-xs {trendClass[advice.trend]}" title="The latest third of these fights against the rest">{trendLabel[advice.trend]}</span>
			{/if}
		</div>
		<p class="mb-2 text-xs text-faint tabular">{advice.sample}</p>
		<p class="text-sm leading-relaxed text-muted">{advice.cause}</p>
		{#if !positive && advice.fix}
			<div class="mt-3 flex gap-2.5 rounded-lg bg-accent/8 p-3 text-sm leading-relaxed">
				<Icon name="wrench" class="mt-0.5 size-4 shrink-0 text-accent" />
				<p><span class="mr-1 font-medium text-accent">Try:</span>{advice.fix}</p>
			</div>
		{/if}
		{#if advice.examples.length}
			<div class="mt-3 flex flex-wrap items-center gap-1.5 text-xs">
				<span class="text-faint">Examples:</span>
				{#each advice.examples as e}
					<a class="chip bg-raised text-muted hover:text-accent" href={fightLink(e.fightId, player, e.t)}
						title="Open the fight on your charts{e.t != null ? ' at this moment' : ''}">
						{dateLabel(e.start)} {timeOfDay(e.start)}{#if e.t != null}&nbsp;@{Math.floor(e.t / 60)}:{String(Math.round(e.t % 60)).padStart(2, '0')}{/if}
					</a>
				{/each}
			</div>
		{/if}
	</div>
</article>
