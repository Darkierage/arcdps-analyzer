<script lang="ts" module>
	import type { FightStatus, Result, Severity } from '#lib/api.ts';

	export const resultClass: Record<Result, string> = {
		win: 'bg-win/15 text-win ring-win/30',
		loss: 'bg-loss/15 text-loss ring-loss/30',
		even: 'bg-even/15 text-even ring-even/30',
		skirmish: 'bg-skirmish/15 text-skirmish ring-skirmish/30'
	};

	export const severityClass: Record<Severity, string> = {
		critical: 'bg-critical/15 text-critical ring-critical/30',
		major: 'bg-major/15 text-major ring-major/30',
		minor: 'bg-minor/15 text-minor ring-minor/30',
		info: 'bg-info/15 text-info ring-info/30',
		positive: 'bg-positive/15 text-positive ring-positive/30'
	};

	export const severityBar: Record<Severity, string> = {
		critical: 'bg-critical',
		major: 'bg-major',
		minor: 'bg-minor',
		info: 'bg-info',
		positive: 'bg-positive'
	};

	export const statusText: Record<FightStatus, string> = {
		queued: 'Queued',
		parsing: 'Parsing',
		analyzing: 'Analyzing',
		done: 'Analyzed',
		skipped: 'Skipped',
		failed: 'Failed'
	};
</script>

<script lang="ts">
	import { resultLabel, severityLabel } from '#lib/format.ts';

	let {
		result = null,
		severity = null,
		status = null,
		size = 'sm'
	}: {
		result?: Result | null;
		severity?: Severity | null;
		status?: FightStatus | null;
		size?: 'sm' | 'lg';
	} = $props();

	const pad = $derived(size === 'lg' ? 'px-2.5 py-1 text-sm' : 'px-1.5 py-0.5 text-xs');
</script>

{#if result}
	<span class="inline-flex items-center rounded-md font-semibold ring-1 ring-inset {pad} {resultClass[result]}">
		{resultLabel[result]}
	</span>
{:else if severity}
	<span class="inline-flex items-center rounded-md font-medium ring-1 ring-inset {pad} {severityClass[severity]}">
		{severityLabel[severity]}
	</span>
{:else if status}
	{#if status === 'queued' || status === 'parsing' || status === 'analyzing'}
		<span class="inline-flex items-center gap-1.5 rounded-md bg-accent/10 font-medium text-accent ring-1 ring-accent/30 ring-inset {pad}">
			<span class="size-2.5 animate-spin rounded-full border-2 border-accent border-t-transparent"></span>
			{statusText[status]}
		</span>
	{:else if status === 'failed'}
		<span class="inline-flex items-center rounded-md bg-loss/10 font-medium text-loss ring-1 ring-loss/30 ring-inset {pad}">Failed</span>
	{:else if status === 'skipped'}
		<span class="inline-flex items-center rounded-md bg-raised font-medium text-faint ring-1 ring-line-2 ring-inset {pad}">Skipped</span>
	{/if}
{/if}
