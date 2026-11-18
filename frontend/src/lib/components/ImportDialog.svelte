<script lang="ts">
	import { api } from '#lib/api.ts';
	import { collectDropped, collectInput } from '#lib/drop.ts';
	import { importer } from '#lib/importer.svelte.ts';
	import { live, toasts } from '#lib/live.svelte.ts';
	import Icon from './Icon.svelte';

	let { open = $bindable(false) }: { open: boolean } = $props();
	// Local date (toISOString would give the UTC date, wrong near midnight).
	const now = new Date();
	const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
	let mode = $state<'files' | 'range'>('files');
	let folder = $state('');
	let since = $state(today);
	let until = $state(today);
	let files = $state<File[]>([]);
	let dragging = $state(false);
	let busy = $state(false);
	let input = $state<HTMLInputElement | null>(null);
	let folderInput = $state<HTMLInputElement | null>(null);

	function addFiles(found: { logs: File[]; ignored: number }) {
		if (found.ignored) toasts.push(`Ignored ${found.ignored} file(s) that aren't arcdps logs`, 'info');
		if (!found.logs.length) {
			toasts.push('No arcdps logs (.zevtc / .evtc) found', 'error');
			return;
		}
		const names = new Set(files.map((f) => f.name));
		files = [...files, ...found.logs.filter((f) => !names.has(f.name))];
	}

	function removeFile(name: string) {
		files = files.filter((f) => f.name !== name);
	}

	function close() {
		open = false;
		files = [];
	}

	async function submitRange() {
		const body = { folder: folder.trim() || undefined, since: since || undefined, until: until || undefined };
		close();
		await importer.startRange(body); // preview, confirm if more than 20 new logs, import
	}

	async function submitFiles() {
		const picked = files;
		close();
		await importer.start(picked); // checks for duplicates, confirms big imports, uploads
	}

	async function submit(e: Event) {
		e.preventDefault();
		busy = true;
		try {
			if (mode === 'range') await submitRange();
			else await submitFiles();
		} catch (err) {
			toasts.error(err);
		} finally {
			busy = false;
		}
	}

	function fmtSize(b: number) {
		return b >= 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.round(b / 1e3)} KB`;
	}
</script>

{#if open}
	<div
		class="fixed inset-0 z-40 grid place-items-center bg-black/60 p-4 backdrop-blur-sm"
		role="presentation"
		onclick={(e) => e.target === e.currentTarget && close()}
	>
		<form class="card w-full max-w-md p-5 shadow-2xl" onsubmit={submit}>
			<div class="mb-4 flex items-center justify-between">
				<h2 class="text-base font-semibold">Import logs</h2>
				<button type="button" class="btn btn-ghost p-1" onclick={close} aria-label="Close">
					<Icon name="x" />
				</button>
			</div>

			<div class="mb-4 flex rounded-lg border border-line-2 p-0.5">
				{#each [['files', 'Pick files'], ['range', 'Date range']] as [m, label]}
					<button
						type="button"
						class="flex-1 rounded-md px-3 py-1.5 text-sm {mode === m ? 'bg-raised font-medium text-text' : 'text-muted hover:text-text'}"
						onclick={() => (mode = m as typeof mode)}>{label}</button
					>
				{/each}
			</div>

			{#if mode === 'files'}
				<input
					bind:this={input}
					type="file"
					accept=".zevtc,.evtc,.zip"
					multiple
					class="hidden"
					onchange={(e) => {
						addFiles(collectInput(e.currentTarget.files));
						e.currentTarget.value = '';
					}}
				/>
				<input
					bind:this={folderInput}
					type="file"
					webkitdirectory
					class="hidden"
					onchange={(e) => {
						addFiles(collectInput(e.currentTarget.files));
						e.currentTarget.value = '';
					}}
				/>
				<button
					type="button"
					data-own-drop
					class="flex w-full flex-col items-center gap-2 rounded-xl border-2 border-dashed px-4 py-7 text-sm transition {dragging
						? 'border-accent bg-accent/10'
						: 'border-line-2 hover:border-accent/60 hover:bg-panel-2'}"
					onclick={() => input?.click()}
					ondragover={(e) => {
						e.preventDefault();
						dragging = true;
					}}
					ondragleave={() => (dragging = false)}
					ondrop={async (e) => {
						e.preventDefault();
						dragging = false;
						if (e.dataTransfer) addFiles(await collectDropped(e.dataTransfer));
					}}
				>
					<Icon name="upload" class="size-6 text-accent" />
					<span><b class="text-text">Choose logs</b> <span class="text-muted">or drop logs / folders here</span></span>
					<span class="text-xs text-faint">.zevtc / .evtc · tip: you can drop onto any page too</span>
				</button>
				<button type="button" class="mt-2 flex items-center gap-1.5 text-xs text-accent hover:underline" onclick={() => folderInput?.click()}>
					<Icon name="folder" class="size-3.5" /> Choose a whole folder instead
				</button>
				{#if files.length}
					<ul class="mt-3 max-h-48 space-y-1 overflow-y-auto">
						{#each files as f (f.name)}
							<li class="flex items-center gap-2 rounded-lg bg-panel-2 px-3 py-1.5 text-sm">
								<Icon name="swords" class="size-3.5 shrink-0 text-faint" />
								<span class="min-w-0 flex-1 truncate">{f.name}</span>
								<span class="tabular text-xs text-faint">{fmtSize(f.size)}</span>
								<button type="button" class="text-faint hover:text-loss" onclick={() => removeFile(f.name)} aria-label="Remove">
									<Icon name="x" class="size-3.5" />
								</button>
							</li>
						{/each}
					</ul>
				{/if}
				<p class="mt-3 text-xs text-faint">
					A single log opens once it's analyzed. Already imported and non-WvW logs are skipped. More than 20
					new logs asks for confirmation first.
				</p>
			{:else}
				<p class="mb-4 text-sm text-muted">
					Logs are grouped into one session per day. Non-WvW and tiny fights are skipped automatically.
				</p>
				<label class="label" for="imp-folder">Folder</label>
				<input
					id="imp-folder"
					class="input mb-3"
					bind:value={folder}
					placeholder={live.recording?.logDir ?? 'arcdps.cbtlogs folder'}
				/>
				<div class="grid grid-cols-2 gap-3">
					<div>
						<label class="label" for="imp-since">From</label>
						<input id="imp-since" class="input" type="date" bind:value={since} />
					</div>
					<div>
						<label class="label" for="imp-until">To</label>
						<input id="imp-until" class="input" type="date" bind:value={until} />
					</div>
				</div>
			{/if}

			<div class="mt-5 flex items-center justify-end gap-2">
				<button type="button" class="btn" onclick={close}>Cancel</button>
				<button class="btn btn-primary" disabled={busy || (mode === 'files' && !files.length)}>
					<Icon name="upload" class="size-4" />
					{mode === 'files' && files.length ? `Import ${files.length} log${files.length === 1 ? '' : 's'}` : 'Import'}
				</button>
			</div>
		</form>
	</div>
{/if}
