<script lang="ts">
	import type { Finding, FindingFocus } from '#lib/api.ts';
	import { duration } from '#lib/format.ts';
	import Badge, { severityBar } from './Badges.svelte';
	import Icon from './Icon.svelte';

	let {
		finding,
		rank = null,
		active = false,
		onfocus,
		onstats
	}: {
		finding: Finding;
		rank?: number | null;
		active?: boolean;
		onfocus?: (w: [number, number] | null) => void;
		onstats?: (f: FindingFocus) => void;
	} = $props();

	const focus = $derived(onstats ? (finding.focus ?? null) : null);

	const positive = $derived(finding.severity === 'positive');
</script>

<article
	id="finding-{finding.key}"
	class="card scroll-mt-4 relative overflow-hidden transition {active ? 'border-accent/60 ring-1 ring-accent/30' : ''}"
>
	<div class="absolute inset-y-0 left-0 w-1 {severityBar[finding.severity]}"></div>
	<div class="py-4 pr-4 pl-5">
		<div class="mb-2 flex items-start gap-3">
			{#if rank != null}
				<div class="tabular mt-0.5 grid size-6 shrink-0 place-items-center rounded-md bg-raised text-xs font-semibold text-muted">
					{rank}
				</div>
			{/if}
			<div class="min-w-0 flex-1">
				<h3 class="leading-snug font-semibold">{finding.title}</h3>
			</div>
			<Badge severity={finding.severity} />
		</div>
		<p class="text-sm leading-relaxed text-muted">{finding.cause}</p>
		{#if !positive && finding.fix}
			<div class="mt-3 flex gap-2.5 rounded-lg bg-accent/8 p-3 text-sm leading-relaxed">
				<Icon name="wrench" class="mt-0.5 size-4 shrink-0 text-accent" />
				<p><span class="mr-1 font-medium text-accent">Change:</span>{finding.fix}</p>
			</div>
		{/if}
		{#if finding.related.length || (finding.window && onfocus) || focus}
			<div class="mt-3 flex flex-wrap items-center gap-2">
				{#each finding.related as r}
					<span class="chip bg-raised text-faint" title="Related finding in the same moment">+ {r}</span>
				{/each}
				{#if focus}
					<button
						class="ml-auto flex items-center gap-1.5 text-xs text-accent hover:underline"
						title="Open the stat table behind this note"
						onclick={() => focus && onstats?.(focus)}
					>
						<Icon name="chart" class="size-3.5" /> See stats
					</button>
				{/if}
				{#if finding.window && onfocus}
					<button
						class="{focus ? '' : 'ml-auto'} flex items-center gap-1.5 text-xs text-accent hover:underline"
						onclick={() => onfocus?.(active ? null : finding.window)}
					>
						<Icon name="target" class="size-3.5" />
						{active ? 'Clear highlight' : `Show ${duration(finding.window[0])}–${duration(finding.window[1])}`}
					</button>
				{/if}
			</div>
		{/if}
	</div>
</article>
