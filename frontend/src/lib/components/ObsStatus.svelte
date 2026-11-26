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
	const tone = $derived(
		!o ? '' : o.state === 'connected' ? (o.recording ? 'text-loss' : 'text-win') : o.state === 'auth' || o.state === 'error' ? 'text-major' : 'text-faint'
	);
</script>

{#if o?.enabled}
	<a href="/settings#videos" class="chip bg-raised {tone} hover:text-text" title={o.error ?? (o.version ? `OBS WebSocket ${o.version}` : 'OBS connection')}>
		<Icon name="video" class="size-3.5" />
		{label}
		{#if o.recording && !o.paused}<span class="size-1.5 animate-pulse rounded-full bg-loss"></span>{/if}
	</a>
{/if}
