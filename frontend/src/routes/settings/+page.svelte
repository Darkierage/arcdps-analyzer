<script lang="ts">
	import { onMount } from 'svelte';
	import { api, type SettingsResponse } from '#lib/api.ts';
	import { live, toasts } from '#lib/live.svelte.ts';
	import Icon from '#lib/components/Icon.svelte';

	let data = $state<SettingsResponse | null>(null);
	let s = $state<any>(null);
	let det = $state<Record<string, any>>({});
	let saving = $state(false);
	let dirty = $state(false);

	async function load() {
		try {
			data = await api.settings();
			s = $state.snapshot(data.settings);
			det = Object.fromEntries(data.detectors.map((d) => [d.name, { enabled: d.enabled, ...d.config }]));
			dirty = false;
		} catch (e) {
			toasts.error(e);
		}
	}
	onMount(load);

	async function save(reanalyze = false) {
		saving = true;
		try {
			// Only store detector values that differ from defaults.
			const detectors: Record<string, any> = {};
			for (const d of data!.detectors) {
				const cur = det[d.name];
				const diff: Record<string, any> = {};
				if (!cur.enabled) diff.enabled = false;
				for (const [k, v] of Object.entries(d.defaults)) if (cur[k] !== v) diff[k] = Number(cur[k]);
				if (Object.keys(diff).length) detectors[d.name] = diff;
			}
			const patch = { ...s, detectors };
			data = await api.saveSettings(patch);
			// detectors is replaced as a whole (not merged) so removed overrides are dropped
			s = $state.snapshot(data.settings);
			dirty = false;
			await live.refresh();
			if (reanalyze) {
				const r = await api.reanalyzeAll();
				toasts.push(`Saved - re-analyzing ${r.queued} fights`, 'success');
			} else toasts.push('Settings saved', 'success');
		} catch (e) {
			toasts.error(e);
		} finally {
			saving = false;
		}
	}

	async function installLlm() {
		try {
			if (dirty) await save();
			live.llm = await api.llmSetup();
		} catch (e) {
			toasts.error(e);
		}
	}

	function resetDetector(name: string) {
		const d = data!.detectors.find((x) => x.name === name)!;
		det[name] = { enabled: true, ...d.defaults };
		dirty = true;
	}

	const llm = $derived(live.llm);
</script>

<!-- Same page container as everywhere else; the form itself stays a readable width. -->
<div class="page" oninput={() => (dirty = true)} onchange={() => (dirty = true)}>
<div class="max-w-4xl">
	<div class="sticky top-0 z-10 -mx-6 mb-5 flex items-center gap-3 bg-bg/90 px-6 py-3 backdrop-blur">
		<h1 class="text-xl font-semibold">Settings</h1>
		{#if dirty}<span class="chip bg-major/15 text-major">Unsaved changes</span>{/if}
		<div class="ml-auto flex gap-2">
			<button class="btn" disabled={saving} onclick={() => save(true)} title="Save and run all detectors again on every fight">
				<Icon name="refresh" class="size-4" /> Save & re-analyze all
			</button>
			<button class="btn btn-primary" disabled={saving || !dirty} onclick={() => save(false)}>Save</button>
		</div>
	</div>

	{#if !s || !data}
		<div class="card h-60 animate-pulse"></div>
	{:else}
		<section class="card mb-5 p-5">
			<h2 class="mb-4 flex items-center gap-2 font-semibold"><Icon name="folder" class="size-4 text-accent" />Logs</h2>
			<label class="label" for="logdir">arcdps log folder</label>
			<input id="logdir" class="input" bind:value={s.log_dir} placeholder={data.defaultLogDir || 'C:\\Users\\…\\Documents\\Guild Wars 2\\addons\\arcdps\\arcdps.cbtlogs'} />
			<p class="mt-1 text-xs {live.recording?.logDirOk ? 'text-faint' : 'text-loss'}">
				{live.recording?.logDirOk ? `Watching: ${data.resolvedLogDir}` : 'Folder not found'}
			</p>
			<label class="label mt-4" for="ei">Elite Insights CLI</label>
			<input id="ei" class="input" bind:value={s.ei_path} placeholder={data.resolvedEiPath} />
			<p class="mt-1 text-xs {live.eiInstalled ? 'text-faint' : 'text-loss'}">
				{live.eiInstalled ? 'Installed' : 'Not found - run scripts/setup_tools.py (bundled in the packaged app).'}
			</p>
		</section>

		<section class="card mb-5 p-5">
			<h2 class="mb-1 font-semibold">Recording & filters</h2>
			<p class="mb-4 text-sm text-muted">Logs that don't look like a zerg fight are kept as "skipped".</p>
			<div class="grid grid-cols-2 gap-4 md:grid-cols-3">
				<div>
					<label class="label" for="f1">Min fight length (s)</label>
					<input id="f1" class="input" type="number" min="0" bind:value={s.filters.min_duration_s} />
				</div>
				<div>
					<label class="label" for="f2">Min enemies</label>
					<input id="f2" class="input" type="number" min="0" bind:value={s.filters.min_enemies} />
				</div>
				<div>
					<label class="label" for="f3">Min squad size</label>
					<input id="f3" class="input" type="number" min="0" bind:value={s.filters.min_squad} />
				</div>
				<div>
					<label class="label" for="r1">Folder check interval (s)</label>
					<input id="r1" class="input" type="number" min="0.5" step="0.5" bind:value={s.recording.poll_interval_s} />
				</div>
				<div>
					<label class="label" for="r2">Log settled after (s)</label>
					<input id="r2" class="input" type="number" min="1" step="0.5" bind:value={s.recording.stable_s} />
				</div>
			</div>
			<label class="mt-4 flex items-center gap-2 text-sm">
				<input type="checkbox" class="accent-accent" bind:checked={s.recording.auto_record} />
				Start/stop recording automatically with the game (Windows)
			</label>
		</section>

		<section class="card mb-5 p-5">
			<h2 class="mb-1 font-semibold">Detectors</h2>
			<p class="mb-4 text-sm text-muted">
				Rules that turn fight data into notes. Tune thresholds to your guild's style, then use
				<b class="text-text">Save & re-analyze all</b>. Note wording can be customized in
				<code class="rounded bg-raised px-1 text-xs">{data.templatesFile}</code>.
			</p>
			<div class="space-y-3">
				{#each data.detectors as d (d.name)}
					{@const cur = det[d.name]}
					<details class="group rounded-lg border border-line bg-panel-2">
						<summary class="flex cursor-pointer list-none items-center gap-3 px-4 py-3">
							<input type="checkbox" class="accent-accent" bind:checked={cur.enabled} onclick={(e) => e.stopPropagation()} />
							<div class="min-w-0 flex-1">
								<div class="text-sm font-medium {cur.enabled ? '' : 'text-faint line-through'}">{d.label}</div>
								<div class="truncate text-xs text-faint">{d.description}</div>
							</div>
							<Icon name="chevron" class="size-4 text-faint transition group-open:rotate-90" />
						</summary>
						<div class="grid grid-cols-2 gap-3 border-t border-line px-4 py-3 md:grid-cols-3">
							{#each Object.keys(d.defaults) as k}
								<div>
									<label class="label normal-case" for="{d.name}-{k}">{k.replaceAll('_', ' ')}</label>
									<input id="{d.name}-{k}" class="input" type="number" step="any" bind:value={cur[k]} />
									{#if cur[k] !== d.defaults[k]}<p class="mt-0.5 text-[11px] text-faint">default {d.defaults[k]}</p>{/if}
								</div>
							{/each}
							<div class="col-span-full">
								<button class="text-xs text-accent hover:underline" onclick={() => resetDetector(d.name)}>Reset to defaults</button>
							</div>
						</div>
					</details>
				{/each}
			</div>
		</section>

		<section class="card mb-10 p-5" id="llm">
			<h2 class="mb-1 flex items-center gap-2 font-semibold"><Icon name="sparkles" class="size-4 text-accent" />Local LLM debrief (optional)</h2>
			<p class="mb-4 text-sm text-muted">
				A small model running on your CPU rewrites the findings into a short debrief. It runs at idle priority with
				few threads, starts only when needed and unloads when idle. The analysis itself never needs it.
			</p>
			<label class="mb-4 flex items-center gap-2 text-sm">
				<input type="checkbox" class="accent-accent" bind:checked={s.llm.enabled} /> Enable LLM debriefs
			</label>
			<div class="grid grid-cols-2 gap-4 md:grid-cols-3">
				<div>
					<label class="label" for="m">Model</label>
					<select id="m" class="input" bind:value={s.llm.model_file}>
						{#each llm?.models ?? [s.llm.model_file] as m}<option value={m}>{m}</option>{/each}
					</select>
				</div>
				<div>
					<label class="label" for="th">CPU threads</label>
					<input id="th" class="input" type="number" min="1" max="16" bind:value={s.llm.threads} />
				</div>
				<div>
					<label class="label" for="gl">GPU layers</label>
					<input id="gl" class="input" type="number" min="0" bind:value={s.llm.gpu_layers} />
					<p class="mt-0.5 text-[11px] text-faint">0 = CPU only (recommended while playing)</p>
				</div>
				<div>
					<label class="label" for="it">Unload after idle (s)</label>
					<input id="it" class="input" type="number" min="30" bind:value={s.llm.idle_timeout_s} />
				</div>
				<div>
					<label class="label" for="qm">Auto-debrief after quiet (min)</label>
					<input id="qm" class="input" type="number" min="1" bind:value={s.llm.quiet_minutes} />
				</div>
			</div>
			<label class="mt-4 flex items-center gap-2 text-sm">
				<input type="checkbox" class="accent-accent" bind:checked={s.llm.auto_debrief} />
				Write debriefs automatically once no new fight was logged for a while (never during fights)
			</label>
			<div class="mt-5 flex flex-wrap items-center gap-3 rounded-lg border border-line bg-panel-2 p-3 text-sm">
				<span class="flex items-center gap-1.5">
					<span class="size-2 rounded-full {llm?.serverInstalled ? 'bg-win' : 'bg-faint'}"></span> llama-server
				</span>
				<span class="flex items-center gap-1.5">
					<span class="size-2 rounded-full {llm?.modelInstalled ? 'bg-win' : 'bg-faint'}"></span> model
				</span>
				<span class="flex items-center gap-1.5">
					<span class="size-2 rounded-full {llm?.running ? 'bg-accent' : 'bg-faint'}"></span>
					{llm?.running ? (llm.busy ? 'writing…' : 'loaded') : 'not loaded'}
				</span>
				{#if llm?.setup.running}
					<span class="text-muted">
						Downloading {llm.setup.step}{llm.setup.progress != null ? ` ${llm.setup.progress}%` : '…'}
					</span>
				{:else if llm?.setup.error}
					<span class="text-loss">{llm.setup.error}</span>
				{/if}
				<div class="ml-auto flex gap-2">
					{#if llm?.running}<button class="btn" onclick={async () => (live.llm = await api.llmUnload())}>Unload</button>{/if}
					{#if !llm?.serverInstalled || !llm?.modelInstalled}
						<button class="btn btn-primary" disabled={llm?.setup.running} onclick={installLlm}>
							Install (~2.5 GB)
						</button>
					{/if}
				</div>
			</div>
		</section>
	{/if}
</div>
</div>
