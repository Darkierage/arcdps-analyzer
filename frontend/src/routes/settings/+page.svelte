<script lang="ts">
	import { onMount } from 'svelte';
	import { api, type OverlayAddonStatus, type SettingsResponse } from '#lib/api.ts';
	import { live, toasts } from '#lib/live.svelte.ts';
	import Icon from '#lib/components/Icon.svelte';
	import { copyDiagnostics, openDataFolder } from '#lib/diagnostics.ts';

	let data = $state<SettingsResponse | null>(null);
	let s = $state<any>(null);
	let det = $state<Record<string, any>>({});
	let saving = $state(false);
	let dirty = $state(false);
	let loadedMode = 'zerg'; // fight_mode when the form was loaded (the header switch can change it too)

	async function load() {
		try {
			data = await api.settings();
			s = $state.snapshot(data.settings);
			loadedMode = s.fight_mode;
			det = Object.fromEntries(data.detectors.map((d) => [d.name, { enabled: d.enabled, ...d.config }]));
			dirty = false;
		} catch (e) {
			toasts.error(e);
		}
	}
	onMount(load);

	// In-game overlay (Nexus addon). The folder is a normal setting (s.gw2_dir); installing
	// stores it too, so the main Save never brings back an old value.
	let overlay = $state<OverlayAddonStatus | null>(null);
	let overlayBusy = $state(false);
	async function loadOverlay() {
		try {
			overlay = await api.overlayAddon();
		} catch (e) {
			toasts.error(e);
		}
	}
	onMount(loadOverlay);

	async function overlayAction(remove: boolean) {
		overlayBusy = true;
		try {
			const was = overlay?.installed;
			overlay = remove ? await api.uninstallOverlayAddon(s.gw2_dir) : await api.installOverlayAddon(s.gw2_dir);
			s.gw2_dir = overlay.override;
			toasts.push(remove ? 'In-game overlay removed' : was ? 'In-game overlay updated' : 'In-game overlay installed', 'success');
		} catch (e) {
			toasts.error(e);
		} finally {
			overlayBusy = false;
		}
	}

	async function save(reanalyze = false) {
		saving = true;
		try {
			// Only store detector values that differ from defaults.
			const detectors: Record<string, any> = {};
			for (const d of data!.detectors) {
				const cur = det[d.name];
				const diff: Record<string, any> = {};
				if (!cur.enabled) diff.enabled = false;
				for (const [k, v] of Object.entries(d.defaults)) {
					// A cleared field (null in Svelte 5) means "use the default", not 0.
					if (cur[k] === null || cur[k] === undefined || cur[k] === '') continue;
					if (Number(cur[k]) !== v) diff[k] = Number(cur[k]);
				}
				if (Object.keys(diff).length) detectors[d.name] = diff;
			}
			const patch: Record<string, any> = { ...s, detectors };
			// Only send the mode if it was changed here, so a later header toggle isn't undone.
			if (s.fight_mode === loadedMode) delete patch.fight_mode;
			data = await api.saveSettings(patch);
			// detectors is replaced as a whole (not merged) so removed overrides are dropped
			s = $state.snapshot(data.settings);
			loadedMode = s.fight_mode;
			dirty = false;
			await live.refresh();
			loadOverlay(); // the Guild Wars 2 folder may have changed
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

	let diagBusy = $state(false);
	async function copyReport() {
		diagBusy = true;
		await copyDiagnostics();
		diagBusy = false;
	}
</script>

<!-- Same page container as everywhere else; the form itself stays a readable width. -->
<div class="page" oninput={() => (dirty = true)} onchange={() => (dirty = true)}>
<div class="max-w-4xl">
	<div class="sticky top-0 z-10 -mx-6 mb-5 flex items-center gap-3 bg-bg/90 px-6 py-3 backdrop-blur">
		<h1 class="text-xl font-semibold">Settings</h1>
		<a href="/welcome" class="text-xs text-accent hover:underline">Run setup again</a>
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
			<h2 class="mb-1 flex items-center gap-2 font-semibold"><Icon name="swords" class="size-4 text-accent" />Fight type</h2>
			<p class="mb-4 text-sm text-muted">
				<b class="text-text">GvG</b>: two guilds fight agreed rounds. When a round is called off, both sides stop,
				walk away and rez everyone. In GvG mode, downs left at the call-off and kills after it are not counted
				against anyone, each round is judged on its own and the result is the round score. The mode is stored per
				fight when it is added, and can be changed later on a fight or session page. The <b class="text-text">GvG</b>
				switch in the header changes the same setting.
			</p>
			<div class="grid grid-cols-2 gap-4 md:grid-cols-3">
				<div>
					<label class="label" for="fm">New fights are analyzed as</label>
					<select id="fm" class="input" bind:value={s.fight_mode}>
						<option value="zerg">Zerg fights</option>
						<option value="gvg">GvG rounds</option>
					</select>
				</div>
				<div>
					<label class="label" for="g1">New round after a lull of (s)</label>
					<input id="g1" class="input" type="number" min="5" step="1" bind:value={s.gvg.round_gap_s} />
					<p class="mt-0.5 text-[11px] text-faint">for logs that hold several rounds</p>
				</div>
				<div>
					<label class="label" for="g2">Kills still count for (s) after the call</label>
					<input id="g2" class="input" type="number" min="0" step="1" bind:value={s.gvg.calloff_grace_s} />
				</div>
			</div>
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

		<section class="card mb-5 p-5" id="overlay">
			<h2 class="mb-1 flex items-center gap-2 font-semibold"><Icon name="monitor" class="size-4 text-accent" />In-game overlay</h2>
			<p class="mb-4 text-sm text-muted">
				A small window inside Guild Wars 2 that shows the latest fight's notes, the session summary and a
				Start/Stop recording button, so you don't have to alt-tab. It's an addon for
				<a class="text-accent hover:underline" href={overlay?.nexusUrl ?? 'https://raidcore.gg/Nexus'} target="_blank" rel="noreferrer">Raidcore Nexus</a>
				and needs this app running. It only displays what this app sends over 127.0.0.1: it doesn't read game memory,
				send keys or post to chat. ArenaNet approves no third-party add-ons, so like arcdps and Nexus it's used at
				your own risk.
			</p>
			<label class="label" for="gw2">Guild Wars 2 folder</label>
			<input id="gw2" class="input" bind:value={s.gw2_dir} placeholder={overlay?.gw2Dir ?? 'C:\\Program Files\\Guild Wars 2'} />
			<p class="mt-1 text-xs {overlay?.gw2Dir ? 'text-faint' : 'text-loss'}">
				{#if overlay?.gw2Dir}Found: {overlay.gw2Dir}{:else if overlay}Gw2-64.exe not found - enter the folder{/if}
			</p>
			<div class="mt-4 flex flex-wrap items-center gap-3 rounded-lg border border-line bg-panel-2 p-3 text-sm">
				<span class="flex items-center gap-1.5">
					<span class="size-2 rounded-full {overlay?.nexus ? 'bg-win' : 'bg-faint'}"></span> Nexus
				</span>
				<span class="flex items-center gap-1.5">
					<span class="size-2 rounded-full {overlay?.installed ? (overlay.upToDate ? 'bg-win' : 'bg-major') : 'bg-faint'}"></span>
					{overlay?.installed ? (overlay.upToDate ? 'Installed' : 'Update available') : 'Not installed'}
				</span>
				{#if overlay && overlay.gw2Dir && !overlay.nexus}
					<span class="text-loss">Install Nexus first, then come back here.</span>
				{:else if overlay && !overlay.bundled}
					<span class="text-loss">This build doesn't include the addon.</span>
				{:else if overlay?.gameRunning}
					<span class="text-muted">Close the game to update or remove it.</span>
				{/if}
				<div class="ml-auto flex gap-2">
					{#if overlay?.installed}
						<button class="btn" disabled={overlayBusy} onclick={() => overlayAction(true)}>Remove</button>
					{/if}
					{#if !overlay?.installed || !overlay.upToDate}
						<button class="btn btn-primary" disabled={overlayBusy || !overlay?.bundled} onclick={() => overlayAction(false)}>
							{overlay?.installed ? 'Update' : 'Install'}
						</button>
					{/if}
				</div>
			</div>
			<p class="mt-2 text-xs text-faint">
				In game: the Quick Access icon or <b>ALT+SHIFT+W</b> toggles the window (rebind it in Nexus). Options are under
				Nexus > Addons > WvW Analyzer.
			</p>
		</section>

		<section class="card mb-5 p-5" id="llm">
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

		<section class="card mb-10 p-5" id="troubleshooting">
			<h2 class="mb-1 flex items-center gap-2 font-semibold"><Icon name="wrench" class="size-4 text-accent" />Troubleshooting</h2>
			<p class="mb-4 text-sm text-muted">
				If something doesn't work, copy the diagnostics and send them to whoever helps you with the app (a Discord
				message is fine). They hold the app version, the setup checks, recent errors and crashes, and the end of the
				app log. Your Windows user name and account names are removed. Nothing is sent anywhere automatically.
			</p>
			<div class="flex flex-wrap items-center gap-3 rounded-lg border border-line bg-panel-2 p-3 text-sm">
				<span class="min-w-0 flex-1 truncate text-xs text-faint" title={live.dataDir}>App folder: {live.dataDir}</span>
				<button class="btn" onclick={openDataFolder}><Icon name="folder" class="size-4" /> Open app folder</button>
				<button class="btn btn-primary" disabled={diagBusy} onclick={copyReport}>Copy diagnostics</button>
			</div>
		</section>
	{/if}
</div>
</div>
