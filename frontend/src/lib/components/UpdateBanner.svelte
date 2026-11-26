<script lang="ts">
	// In-app updater banner (plan 17): a newer release, or an update that did not finish.
	import { api } from '#lib/api.ts';
	import { live, toasts } from '#lib/live.svelte.ts';
	import { bannerKind, downloadProgress, fmtMb, laterVersion, setLater, unfinishedKey } from '#lib/update.ts';
	import Icon from '#lib/components/Icon.svelte';

	let later = $state<string | null>(laterVersion());
	let notesOpen = $state(false);
	let confirming = $state(false);
	let busy = $state(false);

	const u = $derived(live.update);
	const kind = $derived(bannerKind(u, later));
	const version = $derived(u?.latest?.version ?? '');
	const dl = $derived(u?.download ?? null);

	async function run(fn: () => Promise<unknown>) {
		busy = true;
		try {
			const r = await fn();
			if (r && typeof r === 'object' && 'current' in r) live.update = r as typeof live.update;
		} catch (e) {
			toasts.error(e);
		} finally {
			busy = false;
		}
	}

	function hide(key: string) {
		setLater(key);
		later = key;
	}
</script>

{#if kind === 'unfinished' && u?.unfinished}
	<div class="flex items-center gap-3 border-b border-major/30 bg-major/10 px-6 py-2 text-sm">
		<Icon name="alert" class="size-4 shrink-0 text-major" />
		<span class="min-w-0 flex-1">
			The update to {u.unfinished.version} did not finish.
			<span class="text-muted">Run the installer again; your fights and settings are kept.</span>
		</span>
		{#if u.unfinished.canRetry}
			<button class="btn btn-primary" disabled={busy} onclick={() => run(api.retryUpdate)}>Run the installer again</button>
		{/if}
		<a class="btn" href={u.releasesUrl} target="_blank" rel="noreferrer">Release page</a>
		<button class="rounded-md p-1 text-faint hover:text-text" title="Later" aria-label="Later"
			onclick={() => hide(unfinishedKey(u.unfinished!.version))}>
			<Icon name="x" class="size-4" />
		</button>
	</div>
{:else if kind === 'available' && u?.latest}
	<div class="border-b border-accent/30 bg-accent/10 px-6 py-2 text-sm">
		<div class="flex items-center gap-3">
			<Icon name="download" class="size-4 shrink-0 text-accent" />
			<span class="min-w-0 flex-1">
				WvW Analyzer {version} is available
				<span class="text-faint">(you have {u.current})</span>
				<button class="ml-1 text-accent hover:underline" onclick={() => (notesOpen = !notesOpen)}>
					{notesOpen ? 'Hide' : "What's new"}
				</button>
			</span>
			{#if dl?.state === 'downloading'}
				<span class="flex items-center gap-2 text-xs text-muted tabular">
					<span class="size-3 animate-spin rounded-full border-2 border-accent border-t-transparent"></span>
					Downloading {downloadProgress(dl)}
				</span>
			{:else if dl?.state === 'ready'}
				<span class="text-xs text-muted">Closing the app to install the update…</span>
			{:else}
				{#if dl?.state === 'failed'}
					<span class="max-w-80 truncate text-xs text-loss" title={dl.error ?? ''}>Update failed: {dl.error}</span>
				{/if}
				{#if u.canInstall}
					{#if !confirming}
						<button class="btn btn-primary" disabled={busy} onclick={() => (confirming = true)}>
							{dl?.state === 'failed' ? 'Try again' : 'Install and restart'}
						</button>
					{/if}
				{:else}
					<span class="text-xs text-muted">{u.blockedReason}</span>
					<a class="btn" href={u.latest.url} target="_blank" rel="noreferrer">Release page</a>
				{/if}
				<button class="btn" disabled={busy} onclick={() => run(() => api.skipUpdate(version))}>Skip this version</button>
				<button class="rounded-md p-1 text-faint hover:text-text" title="Later" aria-label="Later" onclick={() => hide(version)}>
					<Icon name="x" class="size-4" />
				</button>
			{/if}
		</div>
		{#if confirming && u.canInstall}
			<div class="mt-2 flex flex-wrap items-center gap-3 rounded-lg border border-line bg-panel p-3">
				<span class="min-w-0 flex-1 text-muted">
					The app downloads the update{u.latest.size ? ` (${fmtMb(u.latest.size)} MB)` : ''}, closes, runs the installer and starts again. Your
					fights and settings are kept. If the update fails, start the app and run the installer again, or download it
					from the release page.
				</span>
				<button class="btn" onclick={() => (confirming = false)}>Cancel</button>
				<button class="btn btn-primary" disabled={busy}
					onclick={() => run(async () => { confirming = false; return api.installUpdate(); })}>
					Install now
				</button>
			</div>
		{/if}
		{#if notesOpen}
			<!-- Release notes are plain text (not signed): never rendered as HTML. -->
			<pre class="mt-2 max-h-60 overflow-y-auto rounded-lg border border-line bg-panel p-3 font-sans text-xs whitespace-pre-wrap text-muted">{u.latest.notes || 'No release notes.'}</pre>
		{/if}
	</div>
{/if}
