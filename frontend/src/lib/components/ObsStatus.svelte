<script lang="ts">
	// The OBS chip in the header (only when the connection is turned on in Settings).
	import { live } from '#lib/live.svelte.ts';
	import Icon from './Icon.svelte';

	const o = $derived(live.obs);
	const label = $derived(
		!o
			? ''
			: o.state === 'connected'
				? o.recording
					? o.paused
						? 'OBS paused'
						: 'OBS recording'
					: 'OBS ready'
				: o.state === 'auth'
					? 'OBS: password?'
					: o.state === 'connecting'
						? 'OBS…'
						: 'OBS not running'
	);
	// The recording running now writes more per hour than the limit in Settings (plan 19).
	const big = $derived(!!o && o.recording && !!o.rate?.live && o.rateWarning);
	const tone = $derived(
		!o
			? ''
			: o.state === 'connected'
				? big
					? 'text-major'
					: o.recording
						? 'text-loss'
						: 'text-win'
				: o.state === 'auth' || o.state === 'error'
					? 'text-major'
					: 'text-faint'
	);
	const title = $derived(
		!o
			? ''
			: big && o.rate
				? `OBS is writing about ${o.rate.gbPerHour} GB per hour of recording (${Math.round(o.rate.gbPerHour * 3)} GB for 3 hours). Click for how to make it smaller.`
				: (o.error ?? (o.version ? `OBS WebSocket ${o.version}` : 'OBS connection'))
	);
</script>

{#if o?.enabled}
	<a href="/settings#videos" class="chip bg-raised {tone} hover:text-text" {title}>
		<Icon name="video" class="size-3.5" />
		{label}{#if big && o.rate}<span>· {o.rate.gbPerHour} GB/h</span>{/if}
		{#if o.recording && !o.paused}<span class="size-1.5 animate-pulse rounded-full bg-loss"></span>{/if}
	</a>
{/if}
