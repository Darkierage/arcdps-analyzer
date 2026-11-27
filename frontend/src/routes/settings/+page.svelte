<script lang="ts">
	import { onMount } from 'svelte';
	import { api, type DetectorInfo, type OverlayAddonStatus, type PlayerInfo, type SettingsResponse } from '#lib/api.ts';
	import { live, toasts } from '#lib/live.svelte.ts';
	import Icon from '#lib/components/Icon.svelte';
	import { copyDiagnostics, openDataFolder } from '#lib/diagnostics.ts';

	let data = $state<SettingsResponse | null>(null);
	let s = $state<any>(null);
	let det = $state<Record<string, any>>({});
	let saving = $state(false);
	let dirty = $state(false);
	let loadedMode = 'zerg'; // fight_mode when the form was loaded (the header switch can change it too)
	// Video folders, one per line (stored as a list).
	let folderText = $state('');
	// A new OBS password typed here; empty keeps the stored one (the page never sees it).
	let obsPassword = $state('');
	let obsClear = $state(false);
	let obsTest = $state<{ ok: boolean; version: string | null; error: string | null } | null>(null);
	let obsTesting = $state(false);
	let mapsInstalled = $state<boolean | null>(null);
	let mapsBusy = $state(false);

	async function load() {
		try {
			data = await api.settings();
			s = $state.snapshot(data.settings);
			loadedMode = s.fight_mode;
			folderText = (s.videos?.folders ?? []).join('\n');
			obsPassword = '';
			obsClear = false;
			api.replayMaps().then((m) => (mapsInstalled = m.installed)).catch(() => {});
			det = Object.fromEntries(allRules(data).map((d) => [d.name, { enabled: d.enabled, ...d.config }]));
			dirty = false;
		} catch (e) {
			toasts.error(e);
		}
	}
	onMount(load);

	/** Fight detectors and the personal rules ("My play"): their overrides share one map. */
	function allRules(d: SettingsResponse): (DetectorInfo & { enabledByDefault?: boolean })[] {
		return [...d.detectors, ...(d.personalRules ?? [])];
	}

	// "My play" opens on this account; the list comes from the analyzed fights.
	let players = $state<PlayerInfo[]>([]);
	onMount(async () => {
		try {
			players = (await api.players()).players;
		} catch {
			/* the picker just stays empty */
		}
	});

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
			for (const d of allRules(data!)) {
				const cur = det[d.name];
				const diff: Record<string, any> = {};
				// Some personal rules are off unless turned on; store only a change from that.
				if (cur.enabled !== (d.enabledByDefault ?? true)) diff.enabled = cur.enabled;
				for (const [k, v] of Object.entries(d.defaults)) {
					// A cleared field (null in Svelte 5) means "use the default", not 0.
					if (cur[k] === null || cur[k] === undefined || cur[k] === '') continue;
					if (Number(cur[k]) !== v) diff[k] = Number(cur[k]);
				}
				if (Object.keys(diff).length) detectors[d.name] = diff;
			}
			const patch: Record<string, any> = { ...s, detectors };
			patch.videos = { ...s.videos, folders: folderText.split('\n').map((x: string) => x.trim()).filter(Boolean) };
			patch.obs = { ...s.obs };
			delete patch.obs.password_set;
			if (obsPassword) patch.obs.password = obsPassword;
			else if (obsClear) patch.obs.password = '';
			// Only send the mode if it was changed here, so a later header toggle isn't undone.
			if (s.fight_mode === loadedMode) delete patch.fight_mode;
			delete patch.skipped_update; // set by the update banner, which may have changed it meanwhile
			data = await api.saveSettings(patch);
			// detectors is replaced as a whole (not merged) so removed overrides are dropped
			s = $state.snapshot(data.settings);
			loadedMode = s.fight_mode;
			folderText = (s.videos?.folders ?? []).join('\n');
			obsPassword = '';
			obsClear = false;
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

	async function testObs() {
		obsTesting = true;
		obsTest = null;
		try {
			obsTest = await api.obsTest({ port: Number(s.obs.port) || undefined, password: obsPassword || (obsClear ? '' : undefined) });
		} catch (e) {
			toasts.error(e);
		} finally {
			obsTesting = false;
		}
	}

	async function downloadMaps() {
		mapsBusy = true;
		try {
			mapsInstalled = (await api.downloadReplayMaps()).installed;
			toasts.push('Map images downloaded', 'success');
		} catch (e) {
			toasts.error(e);
		} finally {
			mapsBusy = false;
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
		const d = allRules(data!).find((x) => x.name === name)!;
		det[name] = { enabled: d.enabledByDefault ?? true, ...d.defaults };
		dirty = true;
	}

	const llm = $derived(live.llm);

	// Updates (plan 17): the switch is a normal setting; "Check now" asks right away.
	const upd = $derived(live.update);
	let checking = $state(false);
	async function checkNow() {
		checking = true;
		try {
			live.update = await api.checkUpdate();
			const u = live.update;
			if (u.error) toasts.push(u.error, 'error');
			else if (!u.available) toasts.push(`You have the latest version (${u.current})`, 'success');
		} catch (e) {
			toasts.error(e);
		} finally {
			checking = false;
		}
	}
	function fmtWhen(epoch: number | null): string {
		return epoch ? new Date(epoch * 1000).toLocaleString() : 'never';
	}

	let diagBusy = $state(false);
	async function copyReport() {
		diagBusy = true;
		await copyDiagnostics();
		diagBusy = false;
	}
</script>

{#snippet ruleRow(d: DetectorInfo)}
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
{/snippet}

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
					{@render ruleRow(d)}
				{/each}
			</div>
		</section>

		<section class="card mb-5 p-5" id="my-play">
			<h2 class="mb-1 font-semibold">My play</h2>
			<p class="mb-4 text-sm text-muted">
				Hints for one player, built from your logs: survival against the rest of the squad, output and
				activity against players with the same spec and job. Rules are checked when the page opens, so
				changes here need no re-analysis.
			</p>
			<label class="label" for="myacc">Open on</label>
			<select id="myacc" class="input" bind:value={s.my_account}>
				<option value={null}>The player who recorded the most fights</option>
				{#if s.my_account && !players.some((p) => p.account === s.my_account)}
					<option value={s.my_account}>{s.my_account}</option>
				{/if}
				{#each players as p (p.account)}
					<option value={p.account}>{p.names[0] ?? p.account} ({p.account}) · {p.fights} fight{p.fights === 1 ? "" : "s"}</option>
				{/each}
			</select>
			<p class="mt-4 mb-2 text-xs text-faint">
				Rules marked off by default fired for almost nobody, or no more often than chance, when they were
				calibrated on real fights; turn them on to try them.
			</p>
			<div class="space-y-3">
				{#each data.personalRules ?? [] as d (d.name)}
					{@render ruleRow(d)}
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

		<section class="card mb-5 p-5" id="videos">
			<h2 class="mb-1 flex items-center gap-2 font-semibold"><Icon name="video" class="size-4 text-accent" />Replay and videos</h2>
			<p class="mb-4 text-sm text-muted">
				A fight's Replay tab plays the fight on the map and, when a recording covers it, the video at the same moment.
				Videos are linked on a session's Videos tab and stay where they are: the app never copies or changes them.
			</p>
			<div class="grid gap-4 sm:grid-cols-[1fr_12rem]">
				<div>
					<label class="label" for="vf">Recording folders (one per line)</label>
					<textarea id="vf" class="input min-h-16 font-mono text-xs" bind:value={folderText}
						placeholder={'Empty: your Videos folder\n%USERPROFILE%\\Videos'}></textarea>
					<p class="mt-1 text-xs text-faint">Searched (with one level of subfolders) for recordings to suggest on a session's Videos tab.</p>
				</div>
				<div>
					<label class="label" for="li">Jump lead-in (s)</label>
					<input id="li" class="input" type="number" min="0" max="30" step="0.5" bind:value={s.videos.lead_in_s} />
					<p class="mt-1 text-xs text-faint">A click on the timeline opens the replay this much earlier.</p>
				</div>
			</div>
			<div class="mt-3 flex flex-wrap items-center gap-3 text-sm">
				<span class="flex items-center gap-1.5">
					<span class="size-2 rounded-full {mapsInstalled ? 'bg-win' : 'bg-faint'}"></span>
					Replay map images {mapsInstalled ? 'downloaded' : 'not downloaded'}
				</span>
				{#if mapsInstalled === false}
					<button class="btn !py-1 text-xs" disabled={mapsBusy} onclick={downloadMaps}>{mapsBusy ? 'Downloading…' : 'Download (about 8 MB)'}</button>
				{/if}
				<span class="text-xs text-faint">Elite Insights' map images for Eternal Battlegrounds, the Alpine and Desert Borderlands and Edge of the Mists. Other maps show a grid.</span>
			</div>

			<h3 class="mt-6 mb-1 font-semibold">OBS connection (optional)</h3>
			<p class="mb-3 text-sm text-muted">
				With OBS connected, the app's Record button (and auto-record with the game) also starts and stops OBS recording, and
				each recording is linked to its fights by itself. Without it, link videos by hand. In OBS: <b>Tools → WebSocket
				Server Settings</b> → Enable WebSocket server, then <b>Show Connect Info</b> for the port and password. The app only
				connects to OBS on this PC (127.0.0.1).
			</p>
			<label class="mb-3 flex items-center gap-2 text-sm">
				<input type="checkbox" class="accent-accent" bind:checked={s.obs.enabled} /> Connect to OBS
			</label>
			<div class="grid gap-4 sm:grid-cols-[8rem_1fr]">
				<div>
					<label class="label" for="op">Port</label>
					<input id="op" class="input" type="number" min="1" max="65535" bind:value={s.obs.port} />
				</div>
				<div>
					<label class="label" for="opw">Password</label>
					<div class="flex gap-2">
						<input id="opw" class="input" type="password" autocomplete="off" bind:value={obsPassword}
							placeholder={s.obs.password_set && !obsClear ? 'Saved (type to change)' : 'From OBS: Show Connect Info'} />
						{#if s.obs.password_set && !obsClear}
							<button class="btn" onclick={() => ((obsClear = true), (obsPassword = ''), (dirty = true))} title="Forget the saved password">Clear</button>
						{/if}
					</div>
				</div>
			</div>
			<div class="mt-3 space-y-1.5 text-sm">
				<label class="flex items-center gap-2">
					<input type="checkbox" class="accent-accent" bind:checked={s.obs.control_recording} />
					Start and stop OBS recording with the app's recording
				</label>
				<p class="ml-6 text-xs text-faint">
					The app only stops a recording it started; one you start in OBS yourself keeps running.
				</p>
				<label class="flex items-center gap-2">
					<input type="checkbox" class="accent-accent" bind:checked={s.obs.auto_link} />
					Link OBS recordings to their fights automatically (also ones you start in OBS)
				</label>
			</div>

			<!-- Recording size (plan 19): the app measures what OBS writes; OBS's settings stay the user's. -->
			<h4 class="mt-5 mb-1 text-sm font-semibold">Recording size</h4>
			{#if live.obs?.rate}
				{@const r = live.obs.rate}
				<p class="text-sm {live.obs.rateWarning ? 'text-major' : 'text-muted'}">
					{r.live ? 'This recording' : 'Last recording'}: about <b>{r.gbPerHour} GB per hour</b> ({Math.round(r.gbPerHour * 3)} GB for a
					3-hour evening){live.obs.rateWarning ? '. That is more than needed to review fights.' : '.'}
				</p>
			{:else}
				<p class="text-xs text-faint">Shown once OBS has recorded for a minute while connected.</p>
			{/if}
			<div class="mt-2 rounded border p-3 text-xs text-muted {live.obs?.rateWarning ? 'border-major/50' : 'border-line'}">
				<p class="mb-1">The app doesn't change OBS's settings. For about 3-5 GB per hour at 1080p 60 fps, in OBS <b>Settings → Output</b>:</p>
				<ul class="ml-4 list-disc space-y-0.5">
					<li>a hardware encoder (NVENC, AMD or QuickSync): AV1 if listed, else H.264. Not HEVC: this window can't play it.</li>
					<li>a bitrate cap: 8000-10000 Kbps for H.264, about 6000 for AV1 (Simple mode: Recording Quality "Same as stream" and
						Video Bitrate; Advanced mode: Rate Control CBR or VBR).</li>
					<li>playing at 1440p or 4K: <b>Settings → Video</b>, Output (Scaled) Resolution 1920x1080.</li>
				</ul>
				<p class="mt-1.5">
					Step by step: <a class="text-accent hover:underline" href={live.obs?.sizeGuideUrl ?? '#'} target="_blank" rel="noreferrer">Keep OBS recordings small</a> (README).
				</p>
			</div>
			<div class="mt-3 max-w-xs">
				<label class="label" for="owarn">Warn above (GB per hour, 0: never)</label>
				<input id="owarn" class="input" type="number" min="0" max="1000" step="1" bind:value={s.obs.warn_gb_per_hour} />
			</div>
			<div class="mt-3 flex flex-wrap items-center gap-3">
				<button class="btn" disabled={obsTesting} onclick={testObs}>{obsTesting ? 'Testing…' : 'Test connection'}</button>
				{#if obsTest}
					<span class="text-sm {obsTest.ok ? 'text-win' : 'text-loss'}">
						{obsTest.ok ? `Connected to OBS ${obsTest.version ?? ''}` : obsTest.error}
					</span>
				{:else if live.obs?.enabled}
					<span class="text-xs text-faint">Now: {live.obs.state}{live.obs.recording ? ', recording' : ''}{live.obs.error ? ` - ${live.obs.error}` : ''}</span>
				{/if}
			</div>
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

		<section class="card mb-5 p-5" id="updates">
			<h2 class="mb-1 flex items-center gap-2 font-semibold"><Icon name="download" class="size-4 text-accent" />Updates</h2>
			<p class="mb-4 text-sm text-muted">
				The app asks GitHub for the latest release when it starts and once a day. That request carries no account,
				folder or fight data. Updates are downloaded only when you click <b>Install and restart</b>, and only a release
				signed by the app's author is installed.
			</p>
			<label class="flex items-center gap-2 text-sm">
				<input type="checkbox" class="accent-accent" bind:checked={s.check_updates} /> Check for updates
			</label>
			<div class="mt-4 flex flex-wrap items-center gap-3 rounded-lg border border-line bg-panel-2 p-3 text-sm">
				<span>Version {upd?.current ?? live.version}</span>
				{#if upd?.available && upd.latest}
					<span class="chip bg-accent/15 text-accent">{upd.latest.version} available</span>
				{/if}
				<span class="text-xs text-faint">Last check: {fmtWhen(upd?.lastCheck ?? null)}</span>
				{#if upd?.error}<span class="text-xs text-loss">{upd.error}</span>{/if}
				<div class="ml-auto flex gap-2">
					<a class="btn" href={upd?.releasesUrl ?? '#'} target="_blank" rel="noreferrer">Release page</a>
					<button class="btn btn-primary" disabled={checking || upd?.checking} onclick={checkNow}>
						<Icon name="refresh" class="size-4" /> Check now
					</button>
				</div>
			</div>
			{#if upd?.skipped && upd.latest}
				<p class="mt-2 text-xs text-faint">
					Version {upd.latest.version} is skipped.
					<button class="text-accent hover:underline" onclick={async () => {
						await api.saveSettings({ skipped_update: null });
						live.update = await api.update();
					}}>Show it again</button>
				</p>
			{/if}
		</section>

		<section class="card mb-10 p-5" id="troubleshooting">
			<h2 class="mb-1 flex items-center gap-2 font-semibold"><Icon name="wrench" class="size-4 text-accent" />Troubleshooting</h2>
			<p class="mb-4 text-sm text-muted">
				If something doesn't work, copy the diagnostics and send them to whoever helps you with the app (a Discord
				message is fine). They hold the app version, the setup checks, recent errors and crashes, and the end of the
				app log. Your Windows user name and account names are removed. The diagnostics are never sent anywhere
				automatically.
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
