<script lang="ts">
	import { api } from '#lib/api.ts';
	import { live, toasts } from '#lib/live.svelte.ts';
	import { onDestroy } from 'svelte';
	import Icon from './Icon.svelte';

	let busy = $state(false);
	let now = $state(Date.now() / 1000);
	const timer = setInterval(() => (now = Date.now() / 1000), 1000);
	onDestroy(() => clearInterval(timer));

	const rec = $derived(live.recording);
	const elapsed = $derived(rec?.startedAt ? Math.max(0, now - rec.startedAt) : 0);

	function hms(s: number) {
		const h = Math.floor(s / 3600);
		const m = Math.floor((s % 3600) / 60);
		const sec = Math.floor(s % 60);
		return (h ? `${h}:${String(m).padStart(2, '0')}` : `${m}`) + `:${String(sec).padStart(2, '0')}`;
	}

	async function toggle() {
		busy = true;
		try {
			if (rec?.recording) {
				live.recording = await api.stopRecording();
				toasts.push('Recording stopped', 'info');
			} else {
				live.recording = await api.startRecording();
				toasts.push('Recording - new logs will be analyzed automatically', 'success');
			}
		} catch (e) {
			toasts.error(e);
		} finally {
			busy = false;
		}
	}
</script>

{#if rec?.recording}
	<div class="flex items-center gap-3">
		<div class="flex items-center gap-2 rounded-lg border border-loss/40 bg-loss/10 py-1.5 pr-3 pl-2.5 text-sm">
			<span class="relative flex size-2.5">
				<span class="absolute inline-flex size-full animate-ping rounded-full bg-loss opacity-60"></span>
				<span class="relative inline-flex size-2.5 rounded-full bg-loss"></span>
			</span>
			<span class="font-medium text-loss">Recording</span>
			<span class="tabular text-muted">{hms(elapsed)}</span>
			<span class="text-faint">·</span>
			<span class="tabular text-muted">{rec.fights} fight{rec.fights === 1 ? '' : 's'}</span>
			{#if rec.autoStarted}<span class="chip bg-raised text-faint">auto</span>{/if}
		</div>
		<button class="btn" onclick={toggle} disabled={busy}>
			<Icon name="stop" class="size-3.5" /> Stop
		</button>
		{#if rec.sessionId}
			<a class="text-xs text-accent hover:underline" href="/sessions/{rec.sessionId}">Session →</a>
		{/if}
	</div>
{:else}
	<button
		class="btn btn-primary"
		onclick={toggle}
		disabled={busy || (rec != null && !rec.logDirOk)}
		title={rec && !rec.logDirOk ? 'arcdps log folder not found - set it in Settings' : 'Watch the arcdps folder and analyze each new log'}
	>
		<Icon name="record" class="size-3.5" /> Start recording
	</button>
	{#if rec && !rec.logDirOk}
		<a href="/settings" class="text-xs text-loss hover:underline">Log folder not found</a>
	{/if}
{/if}
