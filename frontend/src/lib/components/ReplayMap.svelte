<script lang="ts">
	// The combat replay map: every actor's position at the clock's time, drawn on a canvas.
	// The parent calls draw(t) each frame; zoom (wheel) and pan (drag) are kept here.
	import { onDestroy, onMount } from 'svelte';
	import type { Replay, ReplayActor } from '#lib/api.ts';
	import { replayMapUrl } from '#lib/api.ts';
	import { profColor } from '#lib/format.ts';
	import { bounds, facingAt, positionAt, stateAt, type ActorState } from '#lib/replay.ts';

	let {
		replay,
		party = 'all',
		follow = $bindable(false),
		mapReady = false,
		height = 520
	}: {
		replay: Replay;
		/** 'all', or a party's group number: the others in the squad are dimmed. */
		party?: string;
		/** Keep the commander in the middle (a drag turns it off). */
		follow?: boolean;
		/** The map image for this fight is downloaded. */
		mapReady?: boolean;
		height?: number;
	} = $props();

	let canvas: HTMLCanvasElement;
	let img: HTMLImageElement | null = null;
	let imgOk = $state(false);
	let lastT = 0;
	// View: world (replay pixel) point at the canvas center and screen pixels per world pixel.
	let cx = 0, cy = 0, scale = 1;
	let hover = $state<{ x: number; y: number; text: string } | null>(null);
	let mouse: [number, number] | null = null;

	const C = { squad: '#7c9cff', ally: '#3ecf8e', enemy: '#f2555a', down: '#f59e42', grid: '#1a2132', text: '#8a93a8' };
	// Draw order: enemies under allies under the squad; the commander last.
	const order = (a: ReplayActor) => (a.kind === 'enemy' ? 0 : a.kind === 'ally' ? 1 : a.commander ? 3 : 2);
	const actors = $derived([...replay.actors].sort((a, b) => order(a) - order(b)));
	const commander = $derived(replay.actors.find((a) => a.kind === 'squad' && a.commander) ?? null);

	export function fit() {
		const own = replay.actors.filter((a) => a.kind !== 'enemy');
		const b = bounds(own.length ? own : replay.actors);
		const w = canvas?.clientWidth || 800, h = canvas?.clientHeight || height;
		if (!b) {
			[cx, cy, scale] = [replay.size[0] / 2, replay.size[1] / 2, Math.min(w / replay.size[0], h / replay.size[1]) || 1];
			return;
		}
		const pad = 1.25;
		const bw = Math.max(b[2] - b[0], 6), bh = Math.max(b[3] - b[1], 6);
		cx = (b[0] + b[2]) / 2;
		cy = (b[1] + b[3]) / 2;
		scale = Math.min(w / (bw * pad), h / (bh * pad));
		draw(lastT);
	}

	function toScreen(x: number, y: number, w: number, h: number): [number, number] {
		return [(x - cx) * scale + w / 2, (y - cy) * scale + h / 2];
	}

	/** Grid step in world pixels: 300, 600, 1200... game units, at least ~48 screen px apart. */
	function gridStep(): { px: number; units: number } {
		let units = 300;
		while (units * replay.inchToPixel * scale < 48 && units < 76800) units *= 2;
		return { px: units * replay.inchToPixel, units };
	}

	function color(a: ReplayActor): string {
		return a.kind === 'enemy' ? C.enemy : a.kind === 'ally' ? C.ally : C.squad;
	}

	export function draw(tSeconds: number) {
		lastT = tSeconds;
		if (!canvas) return;
		const dpr = window.devicePixelRatio || 1;
		const w = canvas.clientWidth, h = canvas.clientHeight;
		if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
			canvas.width = Math.round(w * dpr);
			canvas.height = Math.round(h * dpr);
		}
		const ctx = canvas.getContext('2d');
		if (!ctx) return;
		ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
		ctx.clearRect(0, 0, w, h);
		const t = tSeconds * 1000;
		const poll = replay.pollingMs;

		if (follow && commander) {
			const p = positionAt(commander, t, poll);
			if (p) [cx, cy] = p;
		}

		// Background: the map image, or a grid in game units.
		if (img && imgOk) {
			const [x0, y0] = toScreen(0, 0, w, h);
			ctx.globalAlpha = 0.85;
			ctx.drawImage(img, x0, y0, replay.size[0] * scale, replay.size[1] * scale);
			ctx.globalAlpha = 1;
		} else {
			const g = gridStep();
			const step = g.px * scale;
			if (step > 4) {
				ctx.strokeStyle = C.grid;
				ctx.lineWidth = 1;
				const [ox, oy] = toScreen(0, 0, w, h);
				ctx.beginPath();
				for (let x = ((ox % step) + step) % step; x < w; x += step) {
					ctx.moveTo(Math.round(x) + 0.5, 0);
					ctx.lineTo(Math.round(x) + 0.5, h);
				}
				for (let y = ((oy % step) + step) % step; y < h; y += step) {
					ctx.moveTo(0, Math.round(y) + 0.5);
					ctx.lineTo(w, Math.round(y) + 0.5);
				}
				ctx.stroke();
			}
		}

		// Actors.
		const one = party !== 'all' ? Number(party) : null;
		let near: { d: number; a: ReplayActor; st: ActorState; x: number; y: number } | null = null;
		for (const a of actors) {
			const st = stateAt(a, t);
			if (st === 'absent' || st === 'dc') continue;
			const p = positionAt(a, t, poll);
			if (!p) continue;
			const [x, y] = toScreen(p[0], p[1], w, h);
			if (x < -20 || y < -20 || x > w + 20 || y > h + 20) continue;
			const dim = one != null && a.kind === 'squad' && a.group !== one;
			const r = a.commander && a.kind === 'squad' ? 6.5 : a.kind === 'enemy' ? 4 : 5;
			ctx.globalAlpha = dim ? 0.25 : st === 'dead' ? 0.55 : 1;
			const ring = color(a);
			if (st === 'dead') {
				ctx.strokeStyle = ring;
				ctx.lineWidth = 2;
				ctx.beginPath();
				ctx.moveTo(x - r, y - r);
				ctx.lineTo(x + r, y + r);
				ctx.moveTo(x + r, y - r);
				ctx.lineTo(x - r, y + r);
				ctx.stroke();
			} else {
				ctx.beginPath();
				ctx.arc(x, y, r, 0, Math.PI * 2);
				if (st === 'down') {
					ctx.strokeStyle = C.down;
					ctx.lineWidth = 2;
					ctx.stroke();
				} else {
					ctx.fillStyle = profColor(a.profession);
					ctx.fill();
					ctx.strokeStyle = ring;
					ctx.lineWidth = a.kind === 'enemy' ? 1.5 : 2;
					ctx.stroke();
					// Facing (own side only: enemies would be too busy).
					const f = a.kind !== 'enemy' ? facingAt(a, t, poll) : null;
					if (f != null) {
						const rad = (f * Math.PI) / 180;
						ctx.beginPath();
						ctx.moveTo(x + Math.cos(rad) * r, y + Math.sin(rad) * r);
						ctx.lineTo(x + Math.cos(rad) * (r + 5), y + Math.sin(rad) * (r + 5));
						ctx.stroke();
					}
				}
			}
			if (a.commander && a.kind === 'squad') {
				// The tag: a small diamond above the dot.
				ctx.fillStyle = '#e3c34f';
				ctx.beginPath();
				ctx.moveTo(x, y - r - 11);
				ctx.lineTo(x + 4.5, y - r - 6.5);
				ctx.lineTo(x, y - r - 2);
				ctx.lineTo(x - 4.5, y - r - 6.5);
				ctx.closePath();
				ctx.fill();
			}
			ctx.globalAlpha = 1;
			if (mouse) {
				const d = Math.hypot(mouse[0] - x, mouse[1] - y);
				if (d < 10 && (!near || d < near.d)) near = { d, a, st, x, y };
			}
		}

		// Scale bar (bottom left).
		const g = gridStep();
		const len = g.px * scale;
		ctx.strokeStyle = C.text;
		ctx.fillStyle = C.text;
		ctx.lineWidth = 1.5;
		ctx.beginPath();
		ctx.moveTo(12, h - 14);
		ctx.lineTo(12 + len, h - 14);
		ctx.moveTo(12, h - 18);
		ctx.lineTo(12, h - 10);
		ctx.moveTo(12 + len, h - 18);
		ctx.lineTo(12 + len, h - 10);
		ctx.stroke();
		ctx.font = '11px system-ui, sans-serif';
		ctx.fillText(`${g.units} range`, 16 + len, h - 10);

		if (near) {
			const a = near.a;
			const who = a.kind === 'enemy' ? `Enemy ${a.profession}` : `${a.name} · ${a.profession}${a.group ? ` · Party ${a.group}` : ''}${a.kind === 'ally' ? ' (not in squad)' : ''}`;
			const st = near.st === 'down' ? ' · downed' : near.st === 'dead' ? ' · dead' : '';
			hover = { x: near.x, y: near.y, text: who + st };
		} else hover = null;
	}

	// The map image (downloaded on demand); positions are already in its pixel space.
	$effect(() => {
		const key = replay.map.key;
		imgOk = false;
		img = null;
		if (!key || !mapReady) return;
		const im = new Image();
		im.onload = () => {
			imgOk = true;
			draw(lastT);
		};
		im.src = replayMapUrl(key);
		img = im;
	});

	// Zoom with the wheel around the pointer; drag to pan.
	let drag = $state<{ x: number; y: number; cx: number; cy: number } | null>(null);
	function onWheel(e: WheelEvent) {
		e.preventDefault();
		const rect = canvas.getBoundingClientRect();
		const mx = e.clientX - rect.left, my = e.clientY - rect.top;
		const w = canvas.clientWidth, h = canvas.clientHeight;
		const wx = (mx - w / 2) / scale + cx, wy = (my - h / 2) / scale + cy;
		const k = Math.exp(-e.deltaY * 0.0015);
		scale = Math.min(Math.max(scale * k, 0.05), 400);
		if (!follow) {
			cx = wx - (mx - w / 2) / scale;
			cy = wy - (my - h / 2) / scale;
		}
		draw(lastT);
	}
	function onDown(e: PointerEvent) {
		drag = { x: e.clientX, y: e.clientY, cx, cy };
		canvas.setPointerCapture(e.pointerId);
	}
	function onMove(e: PointerEvent) {
		const rect = canvas.getBoundingClientRect();
		mouse = [e.clientX - rect.left, e.clientY - rect.top];
		if (drag) {
			const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
			if (Math.hypot(dx, dy) > 3) follow = false;
			cx = drag.cx - dx / scale;
			cy = drag.cy - dy / scale;
		}
		draw(lastT);
	}
	function onUp() {
		drag = null;
	}
	function onLeave() {
		mouse = null;
		hover = null;
		draw(lastT);
	}

	let ro: ResizeObserver | null = null;
	onMount(() => {
		fit();
		ro = new ResizeObserver(() => draw(lastT));
		ro.observe(canvas);
		canvas.addEventListener('wheel', onWheel, { passive: false });
	});
	onDestroy(() => {
		ro?.disconnect();
		canvas?.removeEventListener('wheel', onWheel);
	});
</script>

<div class="relative w-full overflow-hidden rounded-lg bg-[#0b0f17]" style="height: {height}px">
	<canvas
		bind:this={canvas}
		class="block h-full w-full touch-none {drag ? 'cursor-grabbing' : 'cursor-grab'}"
		onpointerdown={onDown}
		onpointermove={onMove}
		onpointerup={onUp}
		onpointerleave={onLeave}
	></canvas>
	{#if hover}
		<div
			class="pointer-events-none absolute z-10 -translate-x-1/2 rounded-md border border-line-2 bg-[#1c2335] px-2 py-1 text-xs whitespace-nowrap text-text"
			style="left: {hover.x}px; top: {Math.max(0, hover.y - 34)}px"
		>
			{hover.text}
		</div>
	{/if}
</div>
