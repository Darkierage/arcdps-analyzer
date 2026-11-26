<script lang="ts">
	// The fight page's Replay tab: the combat replay map and the fight's videos, all following
	// one clock, with the fight timeline underneath (click it to jump).
	import { onDestroy, onMount, untrack } from 'svelte';
	import { api, videoUrl, type FightVideos, type Replay, type Timeline, type VideoRow } from '#lib/api.ts';
	import { toasts } from '#lib/live.svelte.ts';
	import { Clock, clockLabel, jumpTarget } from '#lib/replay.ts';
	import { DRIFT_S, inFile, offsetFor, offsetLabel, outsideNote, videoTime } from '#lib/videoSync.ts';
	import FightTimeline from './FightTimeline.svelte';
	import ReplayMap from './ReplayMap.svelte';
	import Icon from './Icon.svelte';

	let {
		fightId,
		timeline,
		professions = {},
		parties = [],
		at = null,
		onmoment
	}: {
		fightId: number;
		timeline: Timeline;
		professions?: Record<string, string>;
		parties?: string[];
		/** Jump request: fight second `t`, minus the lead-in when `lead`; `n` makes a repeat count. */
		at?: { t: number; lead: boolean; n: number } | null;
		/** The replay stopped at a moment (pause / seek): the page keeps it in its URL. */
		onmoment?: (t: number) => void;
	} = $props();

	let replay = $state<Replay | null>(null);
	let error = $state<string | null>(null);
	let videos = $state<FightVideos | null>(null);
	let mapsReady = $state(false);
	let mapsBusy = $state(false);
	let party = $state('all');
	let follow = $state(false);
	let layout = $state<'both' | 'map' | 'video'>('both');
	let now = $state(0); // the clock's time, for the controls and the playhead
	let playing = $state(false);
	let rate = $state(1);
	let mainId = $state<number | null>(null);
	let adjusting = $state<number | null>(null); // video in "Sync here" mode (detached from the clock)

	let mapComp = $state<ReplayMap | null>(null);
	let clock: Clock | null = null;
	let raf = 0;
	let pendingJump: { t: number; lead: boolean } | null = null;
	const els = new Map<number, HTMLVideoElement>();
	let durations = $state<Record<number, number>>({});
	let errors = $state<Record<number, string>>({});
	const reported = new Set<number>();

	const leadS = $derived(videos?.leadInS ?? 3);
	const vids = $derived(videos?.videos ?? []);
	const main = $derived(vids.find((v) => v.id === mainId) ?? vids[0] ?? null);
	const side = $derived(vids.filter((v) => v !== main));
	const showMap = $derived(layout !== 'video' || !vids.length);
	const showVideo = $derived(layout !== 'map' && vids.length > 0);
	const endS = $derived(replay ? replay.durationMs / 1000 : (timeline.t[timeline.t.length - 1] ?? 0));

	async function load() {
		replay = null;
		error = null;
		try {
			const [r, v, m] = await Promise.all([
				api.replay(fightId),
				api.fightVideos(fightId).catch(() => null),
				api.replayMaps().catch(() => null)
			]);
			replay = r;
			videos = v;
			mapsReady = !!m?.installed;
			clock = new Clock(r.durationMs / 1000);
			if (pendingJump) jump(pendingJump.t, pendingJump.lead);
			pendingJump = null;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	$effect(() => {
		void fightId;
		untrack(load);
	});

	// A jump request from the page (Debrief timeline click, ▶ links, ?t=).
	$effect(() => {
		const a = at;
		if (!a) return;
		untrack(() => {
			if (clock && videos !== undefined) jump(a.t, a.lead);
			else pendingJump = { t: a.t, lead: a.lead };
		});
	});

	function jump(t: number, lead: boolean) {
		seek(lead ? jumpTarget(t, leadS) : t);
	}

	function seek(t: number) {
		if (!clock) return;
		clock.seek(t);
		syncVideos(true);
		onmoment?.(clock.time());
	}

	function toggle() {
		if (!clock) return;
		if (clock.playing) {
			clock.pause();
			onmoment?.(clock.time());
		} else clock.play();
		syncVideos(true);
	}

	function setRate(r: number) {
		rate = r;
		clock?.setRate(r);
	}

	function frame() {
		raf = requestAnimationFrame(frame);
		if (!clock) return;
		const t = clock.time();
		playing = clock.playing;
		if (Math.abs(t - now) > 0.03 || !playing) now = t;
		mapComp?.draw(t);
		syncVideos(false);
	}

	/** Keep each video on the clock: play along, and re-seek only when it drifted. */
	function syncVideos(force: boolean) {
		if (!clock || !videos?.fightStartMs) return;
		const t = clock.time();
		for (const v of vids) {
			const el = els.get(v.id);
			if (!el || v.id === adjusting || errors[v.id]) continue;
			const vt = videoTime(v, videos.fightStartMs, t);
			if (!inFile(vt, durations[v.id])) {
				if (!el.paused) el.pause();
				continue;
			}
			el.muted = v.id !== main?.id;
			if (clock.playing) {
				if (el.playbackRate !== clock.rate) el.playbackRate = clock.rate;
				if (force || Math.abs(el.currentTime - vt) > DRIFT_S) el.currentTime = vt;
				if (el.paused) el.play().catch(() => {});
			} else {
				if (!el.paused) el.pause();
				if ((force || Math.abs(el.currentTime - vt) > 0.04) && !el.seeking) el.currentTime = vt;
			}
		}
	}

	function bindVideo(node: HTMLVideoElement, id: number) {
		els.set(id, node);
		const meta = () => {
			const d = node.duration;
			if (!Number.isFinite(d)) return;
			durations = { ...durations, [id]: d };
			const v = vids.find((x) => x.id === id);
			// The file's length tells where it ends (until OBS or a later look says otherwise).
			if (v && !reported.has(id) && v.syncSource !== 'obs') {
				reported.add(id);
				api.updateVideo(id, { durationMs: Math.round(d * 1000) }).catch(() => {});
			}
			syncVideos(true);
		};
		const fail = () => {
			const code = node.error?.code;
			errors = {
				...errors,
				[id]:
					code === 4
						? "This video's format doesn't play in the app (often HEVC/H.265, or MKV). In OBS: File → Remux Recordings to MP4, or record with H.264 or AV1."
						: 'The video could not be loaded (moved or deleted?).'
			};
		};
		node.addEventListener('loadedmetadata', meta);
		node.addEventListener('error', fail);
		return {
			destroy() {
				els.delete(id);
				node.removeEventListener('loadedmetadata', meta);
				node.removeEventListener('error', fail);
			}
		};
	}

	async function nudge(v: VideoRow, ms: number) {
		try {
			const row = await api.updateVideo(v.id, { offsetMs: v.offsetMs + ms, manual: true });
			replaceRow(row);
			syncVideos(true);
		} catch (e) {
			toasts.error(e);
		}
	}

	function startAdjust(v: VideoRow) {
		clock?.pause();
		adjusting = v.id;
		const el = els.get(v.id);
		if (el) el.muted = false;
	}

	async function saveAdjust(v: VideoRow) {
		const el = els.get(v.id);
		if (!el || !clock || !videos?.fightStartMs) return;
		try {
			const offsetMs = offsetFor(v, videos.fightStartMs, clock.time(), el.currentTime);
			const row = await api.updateVideo(v.id, { offsetMs, manual: true });
			replaceRow(row);
			el.pause();
			adjusting = null;
			syncVideos(true);
			toasts.push(`Synced: every fight in this video moved by ${offsetLabel(row.offsetMs - v.offsetMs)}`, 'success');
		} catch (e) {
			toasts.error(e);
		}
	}

	function cancelAdjust() {
		const el = els.get(adjusting ?? -1);
		el?.pause();
		adjusting = null;
		syncVideos(true);
	}

	function replaceRow(row: VideoRow) {
		if (!videos) return;
		videos = { ...videos, videos: videos.videos.map((x) => (x.id === row.id ? { ...x, ...row } : x)) };
	}

	async function downloadMaps() {
		mapsBusy = true;
		try {
			mapsReady = (await api.downloadReplayMaps()).installed;
		} catch (e) {
			toasts.error(e);
		} finally {
			mapsBusy = false;
		}
	}

	function onKey(e: KeyboardEvent) {
		const tag = (e.target as HTMLElement | null)?.tagName;
		if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA' || adjusting != null) return;
		if (e.key === ' ') {
			e.preventDefault();
			toggle();
		} else if (e.key === 'ArrowLeft') {
			e.preventDefault();
			seek((clock?.time() ?? 0) - 5);
		} else if (e.key === 'ArrowRight') {
			e.preventDefault();
			seek((clock?.time() ?? 0) + 5);
		}
	}

	onMount(() => {
		raf = requestAnimationFrame(frame);
		window.addEventListener('keydown', onKey);
	});
	onDestroy(() => {
		cancelAnimationFrame(raf);
		window.removeEventListener('keydown', onKey);
		for (const el of els.values()) el.pause();
	});

	const note = (v: VideoRow) => {
		if (!videos?.fightStartMs) return null;
		return outsideNote(videoTime(v, videos.fightStartMs, now), durations[v.id]);
	};
	const sourceLabel: Record<string, string> = {
		obs: 'synced by OBS',
		filename: 'synced from the file name',
		filetime: 'synced from the file time',
		manual: 'synced by hand'
	};
</script>

{#if error}
	<div class="card p-5 text-sm text-muted">{error}</div>
{:else if !replay}
	<div class="card h-[520px] animate-pulse"></div>
{:else}
	<div class="card p-3">
		<!-- Controls -->
		<div class="mb-3 flex flex-wrap items-center gap-2">
			<button class="btn" onclick={() => seek(now - 5)} title="Back 5 s (←)">◀ 5s</button>
			<button class="btn btn-primary w-20 justify-center" onclick={toggle} title="Play / pause (space)">
				<Icon name={playing ? 'pause' : 'play'} class="size-4" />{playing ? 'Pause' : 'Play'}
			</button>
			<button class="btn" onclick={() => seek(now + 5)} title="Forward 5 s (→)">5s ▶</button>
			<div class="ml-1 flex rounded-lg border border-line-2 p-0.5">
				{#each [0.5, 1, 2, 4] as r}
					<button class="rounded-md px-2 py-1 text-xs {rate === r ? 'bg-raised text-text' : 'text-muted hover:text-text'}" onclick={() => setRate(r)}>{r}×</button>
				{/each}
			</div>
			<span class="tabular ml-2 text-sm">{clockLabel(now)} <span class="text-faint">/ {clockLabel(endS)}</span></span>
			<div class="ml-auto flex flex-wrap items-center gap-2">
				{#if showMap}
					<label class="flex items-center gap-1.5 text-xs text-muted">
						<input type="checkbox" class="accent-accent" bind:checked={follow} /> Follow tag
					</label>
					<select class="input !w-auto !py-1 text-xs" bind:value={party} aria-label="Highlight a party">
						<option value="all">All parties</option>
						{#each parties as g}<option value={g}>Party {g}</option>{/each}
					</select>
					<button class="btn !py-1 text-xs" onclick={() => mapComp?.fit()} title="Zoom to the squad">Fit</button>
				{/if}
				{#if vids.length}
					<div class="flex rounded-lg border border-line-2 p-0.5">
						{#each [['map', 'Map'], ['video', 'Video'], ['both', 'Both']] as [k, label]}
							<button class="rounded-md px-2 py-1 text-xs {layout === k ? 'bg-raised text-text' : 'text-muted hover:text-text'}"
								onclick={() => (layout = k as typeof layout)}>{label}</button>
						{/each}
					</div>
				{/if}
			</div>
		</div>

		<input
			type="range"
			class="mb-3 w-full accent-accent"
			min="0"
			max={endS}
			step="0.1"
			value={now}
			oninput={(e) => seek(Number(e.currentTarget.value))}
			aria-label="Replay position"
		/>

		<div class="grid gap-3 {showMap && showVideo ? 'lg:grid-cols-2' : ''}">
			{#if showMap}
				<div>
					<ReplayMap bind:this={mapComp} {replay} {party} bind:follow mapReady={mapsReady} height={showVideo ? 460 : 560} />
					<div class="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-faint">
						<span><span class="mr-1 inline-block size-2 rounded-full border-2 border-[#7c9cff]"></span>Squad</span>
						<span><span class="mr-1 inline-block size-2 rounded-full border-2 border-[#3ecf8e]"></span>Allies</span>
						<span><span class="mr-1 inline-block size-2 rounded-full border-2 border-[#f2555a]"></span>Enemies</span>
						<span class="text-[#f59e42]">○ downed</span><span>✕ dead</span>
						<span>Wheel: zoom · drag: pan</span>
						{#if replay.map.key && !mapsReady}
							<button class="text-accent hover:underline disabled:opacity-50" disabled={mapsBusy} onclick={downloadMaps}>
								{mapsBusy ? 'Downloading the map images…' : 'Show the map: download the map images (about 8 MB, once)'}
							</button>
						{:else if !replay.map.key}
							<span>No map image for this map: grid in game units.</span>
						{/if}
					</div>
				</div>
			{/if}

			{#if showVideo}
				<div class="space-y-2">
					{#if main}{@render tile(main, true)}{/if}
					{#if side.length}
						<div class="grid grid-cols-2 gap-2">
							{#each side as v (v.id)}{@render tile(v, false)}{/each}
						</div>
					{/if}
				</div>
			{/if}
		</div>

		<div class="mt-3">
			<FightTimeline {timeline} {professions} height={260} playhead={now} onseek={(t) => seek(t)} />
			<p class="mt-1 text-xs text-faint">Click the timeline to jump to that second.</p>
		</div>
	</div>
	{#if !vids.length}
		<p class="mt-2 text-xs text-faint">
			No video covers this fight. Link recordings on the session's Videos tab, or connect OBS in Settings to link them
			automatically.
		</p>
	{/if}
{/if}

{#snippet tile(vv: VideoRow, isMain: boolean)}
	{@const off = note(vv)}
	<div>
		<div class="relative overflow-hidden rounded-lg bg-black">
			<!-- svelte-ignore a11y_media_has_caption -->
			<video
				use:bindVideo={vv.id}
				src={videoUrl(vv.id)}
				preload="metadata"
				playsinline
				controls={adjusting === vv.id}
				class="block aspect-video w-full {isMain ? '' : 'cursor-pointer'}"
				onclick={() => !isMain && adjusting == null && (mainId = vv.id)}
			></video>
			{#if errors[vv.id]}
				<div class="absolute inset-0 grid place-items-center bg-black/80 p-4 text-center text-xs text-muted">{errors[vv.id]}</div>
			{:else if off && adjusting !== vv.id}
				<div class="absolute inset-0 grid place-items-center bg-black/70 p-3 text-center text-xs text-muted">
					{vv.label || vv.name}: {off}
				</div>
			{/if}
		</div>
		<div class="mt-1 flex flex-wrap items-center gap-1.5 text-xs">
			<span class="truncate font-medium" title={vv.path ?? ''}>{vv.label || vv.name}</span>
			{#if !isMain}<span class="text-faint">(click to make it the main one)</span>{/if}
			<span class="text-faint" title="How the start time was found; the offset is your correction">
				{sourceLabel[vv.syncSource]}{vv.offsetMs ? ` ${offsetLabel(vv.offsetMs)}` : ''}
			</span>
			{#if vv.approximate}<span class="chip bg-major/15 text-major" title="The start time may be off: use Sync here">approximate</span>{/if}
			<span class="ml-auto flex flex-wrap items-center gap-1">
				{#if adjusting === vv.id}
					<span class="text-muted">Find the frame the replay shows ({clockLabel(now)}), then</span>
					<button class="btn btn-primary !px-2 !py-0.5 text-xs" onclick={() => saveAdjust(vv)}>Save sync</button>
					<button class="btn !px-2 !py-0.5 text-xs" onclick={cancelAdjust}>Cancel</button>
				{:else}
					<button class="btn !px-1.5 !py-0.5 text-xs" onclick={() => nudge(vv, -500)} title="Show this video 0.5 s earlier, in every fight it covers">−0.5s</button>
					<button class="btn !px-1.5 !py-0.5 text-xs" onclick={() => nudge(vv, 500)} title="Show this video 0.5 s later, in every fight it covers">+0.5s</button>
					<button class="btn !px-2 !py-0.5 text-xs" onclick={() => startAdjust(vv)}
						title="Pause, scrub this video to the moment the replay shows, and save: fixes every fight in this video">Sync here</button>
				{/if}
			</span>
		</div>
	</div>
{/snippet}
