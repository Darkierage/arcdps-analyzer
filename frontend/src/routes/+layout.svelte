<script lang="ts">
	import './layout.css';
	import favicon from '#lib/assets/favicon.svg';
	import type { LayoutProps } from './$types';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { live } from '#lib/live.svelte.ts';
	import RecordButton from '#lib/components/RecordButton.svelte';
	import ImportDialog from '#lib/components/ImportDialog.svelte';
	import Toasts from '#lib/components/Toasts.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import GlobalDrop from '#lib/components/GlobalDrop.svelte';
	import ImportConfirm from '#lib/components/ImportConfirm.svelte';
	import { importer } from '#lib/importer.svelte.ts';
	import { api } from '#lib/api.ts';
	import { toasts } from '#lib/live.svelte.ts';

	let { children }: LayoutProps = $props();
	let importOpen = $state(false);

	async function cancelImports() {
		importer.cancel(); // stop uploading the rest
		try {
			const { cancelled } = await api.cancelQueue();
			if (cancelled) toasts.push(`Cancelled ${cancelled} queued log${cancelled === 1 ? '' : 's'}`, 'info');
		} catch (e) {
			toasts.error(e);
		}
	}

	onMount(() => live.start());

	const nav = [
		{ href: '/', label: 'Fights', icon: 'swords', match: (p: string) => p === '/' || p.startsWith('/fights') },
		{ href: '/sessions', label: 'Sessions', icon: 'calendar', match: (p: string) => p.startsWith('/sessions') },
		{ href: '/settings', label: 'Settings', icon: 'settings', match: (p: string) => p.startsWith('/settings') }
	];
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<title>WvW Analyzer</title>
</svelte:head>

<div class="flex h-screen overflow-hidden">
	<aside class="flex w-56 shrink-0 flex-col border-r border-line bg-panel">
		<div class="flex items-center gap-2.5 px-5 pt-5 pb-6">
			<div class="grid size-8 place-items-center rounded-lg bg-gradient-to-br from-accent to-[#a77cff] shadow-lg shadow-accent/20">
				<Icon name="shield" class="size-4.5 text-white" />
			</div>
			<div>
				<div class="text-sm font-semibold leading-tight">WvW Analyzer</div>
				<div class="text-[11px] text-faint">zerg fight debriefs</div>
			</div>
		</div>
		<nav class="flex flex-col gap-0.5 px-3">
			{#each nav as item}
				{@const active = item.match(page.url.pathname)}
				<a
					href={item.href}
					class="flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition {active
						? 'bg-raised font-medium text-text'
						: 'text-muted hover:bg-panel-2 hover:text-text'}"
				>
					<Icon name={item.icon} class="size-4 {active ? 'text-accent' : ''}" />
					{item.label}
				</a>
			{/each}
		</nav>
		<div class="mt-auto space-y-2 px-5 pb-5 text-[11px] text-faint">
			{#if !live.eiInstalled}
				<a href="/settings" class="block rounded-lg border border-loss/40 bg-loss/10 p-2 text-loss">
					Elite Insights is not installed - see Settings.
				</a>
			{/if}
			<div class="flex items-center gap-1.5">
				<span class="size-1.5 rounded-full {live.connected ? 'bg-win' : 'bg-loss'}"></span>
				{live.connected ? 'Connected' : 'Reconnecting…'}
				{#if live.version}<span class="ml-auto">v{live.version}</span>{/if}
			</div>
		</div>
	</aside>

	<div class="flex min-w-0 flex-1 flex-col">
		<header class="flex h-14 shrink-0 items-center gap-3 border-b border-line bg-panel/60 px-6 backdrop-blur">
			<RecordButton />
			{#if importer.phase === 'checking'}
				<div class="flex items-center gap-2 text-xs text-muted">
					<span class="size-3 animate-spin rounded-full border-2 border-accent border-t-transparent"></span>
					Checking dropped logs…
				</div>
			{:else if importer.phase === 'uploading' || live.queue.pending > 0}
				<div class="flex items-center gap-2 text-xs text-muted">
					<span class="size-3 animate-spin rounded-full border-2 border-accent border-t-transparent"></span>
					{#if importer.phase === 'uploading'}
						<span class="tabular">Importing {importer.done}/{importer.total}</span>
						{#if live.queue.pending > 0}<span class="text-faint">·</span>{/if}
					{/if}
					{#if live.queue.pending > 0}
						<span class="tabular">Processing {live.queue.pending} log{live.queue.pending === 1 ? '' : 's'}</span>
					{/if}
					{#if importer.phase === 'uploading' || (live.queue.cancellable ?? 0) > 0}
						<button class="ml-1 rounded-md px-1.5 py-0.5 text-loss hover:bg-loss/10" onclick={cancelImports}
							title="Stop importing; logs already analyzed are kept, queued imports are dropped (recorded fights are never cancelled)">
							Cancel
						</button>
					{/if}
				</div>
			{/if}
			<div class="ml-auto flex items-center gap-2">
				<button class="btn" onclick={() => (importOpen = true)}>
					<Icon name="upload" class="size-4" /> Import logs
				</button>
			</div>
		</header>
		<main class="min-h-0 flex-1 overflow-y-auto">
			{@render children()}
		</main>
	</div>
</div>

<ImportDialog bind:open={importOpen} />
<ImportConfirm />
<GlobalDrop />
<Toasts />
