<script lang="ts">
	import type { PlayerDown } from '#lib/api.ts';
	import { dateLabel, timeOfDay } from '#lib/format.ts';
	import Icon from './Icon.svelte';

	/** Downs, one line each with the hint that matched it. `href` links a down to its moment;
	 * `onpick` (the fight page) shows it in place instead. */
	let {
		downs,
		href,
		onpick,
		showFight = false
	}: {
		downs: PlayerDown[];
		href?: (d: PlayerDown) => string;
		onpick?: (d: PlayerDown) => void;
		showFight?: boolean;
	} = $props();
</script>

<ul class="divide-y divide-line">
	{#each downs as d (`${d.fightId}-${d.key}-${d.t}`)}
		<li class="flex gap-3 py-2.5">
			<span class="mt-0.5 text-sm {d.died ? 'text-loss' : 'text-major'}" title={d.died ? 'Died' : 'Rallied or was revived'}>{d.died ? '✕' : '▲'}</span>
			<div class="min-w-0 flex-1">
				<div class="flex flex-wrap items-baseline gap-x-2">
					{#if onpick}
						<button class="text-left text-sm font-medium hover:text-accent" onclick={() => onpick?.(d)}>{d.hint.title}</button>
					{:else if href}
						<a class="text-sm font-medium hover:text-accent" href={href(d)}>{d.hint.title}</a>
					{:else}
						<span class="text-sm font-medium">{d.hint.title}</span>
					{/if}
					{#if showFight}<span class="text-xs text-faint">{dateLabel(d.start)} {timeOfDay(d.start)}{d.map ? ` · ${d.map}` : ''}</span>{/if}
				</div>
				<p class="text-xs leading-relaxed text-muted">{d.hint.cause}</p>
				{#if d.hint.fix}
					<p class="mt-0.5 flex items-start gap-1.5 text-xs text-accent"><Icon name="wrench" class="mt-px size-3 shrink-0" />{d.hint.fix}</p>
				{/if}
				{#if d.recap}
					<p class="mt-0.5 text-[11px] text-faint" title="From the death recap: the hits that took you down">
						{d.recap.span}s from first to last hit{d.recap.enemies ? `, ${d.recap.enemies} enemies` : ''}:
						{d.recap.top.map((x) => `${x.skill} ${Math.round(x.share * 100)}%${x.spec ? ` (${x.spec})` : ''}`).join(', ')}
					</p>
				{/if}
			</div>
		</li>
	{/each}
</ul>
