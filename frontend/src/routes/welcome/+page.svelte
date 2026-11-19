<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { api, type SelfTest } from '#lib/api.ts';
	import { live, toasts } from '#lib/live.svelte.ts';
	import Icon from '#lib/components/Icon.svelte';

	let test = $state<SelfTest | null>(null);
	let folder = $state('');
	let saving = $state(false);
	let finishing = $state(false);
	// pywebview exposes window.pywebview.api in the desktop window only.
	const desktop = typeof window !== 'undefined' && 'pywebview' in window;

	async function run() {
		try {
			test = await api.selftest();
			if (!folder) folder = test.logDir.path ?? test.logDir.detected ?? '';
		} catch (e) {
			toasts.error(e);
		}
	}
	onMount(run);

	async function browse() {
		const picked = await (window as any).pywebview?.api?.pick_folder?.();
		if (picked) folder = picked;
	}

	async function saveFolder() {
		saving = true;
		try {
			await api.saveSettings({ log_dir: folder.trim() || null });
			await run();
			await live.refresh();
		} catch (e) {
			toasts.error(e);
		} finally {
			saving = false;
		}
	}

	async function installLlm() {
		try {
			live.llm = await api.llmSetup();
		} catch (e) {
			toasts.error(e);
		}
	}

	async function finish() {
		finishing = true;
		try {
			await api.saveSettings({ onboarded: true });
			await live.refresh();
			toasts.push('All set - press Start recording before your next raid', 'success', 7000);
			goto('/');
		} catch (e) {
			toasts.error(e);
		} finally {
			finishing = false;
		}
	}

	const llm = $derived(live.llm ?? test?.llm ?? null);
	const ready = $derived(!!test?.logDir.ok && !!test?.elite.ok);
</script>

<div class="page">
	<div class="mx-auto max-w-3xl">
		<div class="mb-6 flex items-center gap-3">
			<div class="grid size-11 place-items-center rounded-xl bg-gradient-to-br from-accent to-[#a77cff] shadow-lg shadow-accent/20">
				<Icon name="shield" class="size-6 text-white" />
			</div>
			<div>
				<h1 class="text-2xl font-semibold">Welcome to WvW Analyzer</h1>
				<p class="text-sm text-muted">Two quick checks and you're ready for your next raid.</p>
			</div>
		</div>

		{#if !test}
			<div class="card h-60 animate-pulse"></div>
		{:else}
			<!-- 1. Log folder -->
			<section class="card mb-4 p-5">
				<div class="mb-2 flex items-center gap-2">
					<span class="grid size-6 place-items-center rounded-full text-xs font-semibold {test.logDir.ok ? 'bg-win/20 text-win' : 'bg-major/20 text-major'}">
						{#if test.logDir.ok}<Icon name="check" class="size-3.5" />{:else}1{/if}
					</span>
					<h2 class="font-semibold">arcdps log folder</h2>
				</div>
				{#if test.logDir.ok}
					<p class="mb-3 text-sm text-muted">
						Found <b class="text-text">{test.logDir.wvwLogs}</b> WvW logs in
						<code class="rounded bg-raised px-1 text-xs">{test.logDir.path}</code>.
					</p>
				{:else}
					<p class="mb-3 text-sm text-muted">
						Couldn't find the arcdps log folder. It's usually
						<code class="rounded bg-raised px-1 text-xs">Documents\Guild Wars 2\addons\arcdps\arcdps.cbtlogs</code>.
						Make sure arcdps is installed and has saved at least one log.
					</p>
				{/if}
				<div class="flex gap-2">
					<input class="input" bind:value={folder} placeholder="arcdps.cbtlogs folder" />
					{#if desktop}<button class="btn" onclick={browse}><Icon name="folder" class="size-4" /> Browse…</button>{/if}
					<button class="btn" onclick={saveFolder} disabled={saving || folder === (test.logDir.path ?? '')}>Use this folder</button>
				</div>
			</section>

			<!-- 2. Elite Insights -->
			<section class="card mb-4 p-5">
				<div class="mb-2 flex items-center gap-2">
					<span class="grid size-6 place-items-center rounded-full text-xs font-semibold {test.elite.ok ? 'bg-win/20 text-win' : 'bg-loss/20 text-loss'}">
						{#if test.elite.ok}<Icon name="check" class="size-3.5" />{:else}2{/if}
					</span>
					<h2 class="font-semibold">Log parser (Elite Insights)</h2>
				</div>
				{#if test.elite.ok}
					<p class="text-sm text-muted">
						Ready - Elite Insights {test.elite.version} on .NET {test.elite.runtime}{test.elite.private
							? ' (bundled with the app, nothing else to install)'
							: ''}.
					</p>
				{:else}
					<p class="text-sm text-loss">{test.elite.error}</p>
					<p class="mt-1 text-xs text-faint">Reinstalling WvW Analyzer usually fixes this.</p>
				{/if}
			</section>

			<!-- 3. Optional LLM -->
			<section class="card mb-6 p-5">
				<div class="mb-2 flex items-center gap-2">
					<span class="grid size-6 place-items-center rounded-full bg-raised text-xs text-faint">
						<Icon name="sparkles" class="size-3.5" />
					</span>
					<h2 class="font-semibold">Written debriefs <span class="text-xs font-normal text-faint">(optional)</span></h2>
				</div>
				<p class="text-sm text-muted">
					The analysis and its notes work without this. Optionally, a small local AI model (about 2.5 GB download) can turn
					the notes into a paste-ready squad debrief. It runs on your CPU at low priority and never during fights.
				</p>
				{#if llm?.serverInstalled && llm?.modelInstalled}
					<p class="mt-3 flex items-center gap-1.5 text-sm text-win"><Icon name="check" class="size-4" /> Installed - enable it in Settings.</p>
				{:else if llm?.setup.running}
					<p class="mt-3 text-sm text-muted">
						Downloading {llm.setup.step}{llm.setup.progress != null ? ` ${llm.setup.progress}%` : '…'} - you can finish setup meanwhile.
					</p>
				{:else}
					<button class="btn mt-3" onclick={installLlm}>Install (~2.5 GB)</button>
					{#if llm?.setup.error}<p class="mt-2 text-xs text-loss">{llm.setup.error}</p>{/if}
				{/if}
			</section>

			<div class="flex items-center gap-3">
				<button class="btn btn-primary px-5 py-2" onclick={finish} disabled={finishing || !ready}>
					{ready ? 'Finish setup' : 'Fix the steps above to continue'}
				</button>
				{#if !ready}
					<button class="text-xs text-faint hover:text-text" onclick={finish}>Skip for now</button>
				{/if}
				<span class="ml-auto text-xs text-faint">After setup: press <b>Start recording</b> before a raid, or import logs you already have.</span>
			</div>
		{/if}
	</div>
</div>
