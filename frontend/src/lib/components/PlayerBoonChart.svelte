<script lang="ts">
	// One player's boons over a fight: a lane per boon, filled while the player had it (might and
	// stability shaded by stacks), plus lanes for the time they were downed or dead.
	import { onDestroy, onMount } from 'svelte';
	import { graphic, init, use, type EChartsType } from 'echarts/core';
	import { CustomChart, LineChart } from 'echarts/charts';
	import { DataZoomComponent, GridComponent, MarkAreaComponent, TooltipComponent } from 'echarts/components';
	import { CanvasRenderer } from 'echarts/renderers';
	import type { PlayerSeries, Timeline } from '#lib/api.ts';
	import { duration } from '#lib/format.ts';
	import { BOON_COLORS } from '#lib/boonColors.ts';
	import { trackPointer } from '#lib/timelineEvents.ts';

	use([CustomChart, LineChart, GridComponent, TooltipComponent, MarkAreaComponent, DataZoomComponent, CanvasRenderer]);

	let {
		series,
		timeline
	}: {
		series: PlayerSeries;
		/** The fight's timeline: boon names in display order, GvG rounds. */
		timeline: Timeline;
	} = $props();

	let el: HTMLDivElement;
	let chart: EChartsType | null = null;
	let ro: ResizeObserver | null = null;
	let pointerX: () => number | null = () => null;

	const C = { text: '#8a93a8', line: '#222a3d', down: '#f59e42', dead: '#f2555a' };
	// Stacks at which a lane is fully opaque.
	const FULL: Record<string, number> = { '740': 25, '1122': 10 };
	const LANE_H = 22;

	const names = $derived(timeline.boonNames ?? []);
	const lanes = $derived([...names.map(([, n]) => n), 'Downed', 'Dead']);
	const height = $derived(lanes.length * LANE_H + 70);

	/** Runs covering time x, for the tooltip. */
	function at(runs: number[][] | undefined, x: number): number[] | undefined {
		return runs?.find((r) => r[0] <= x && x < r[1]);
	}

	function option() {
		const s = series;
		const t = s.t;
		const tEnd = t[t.length - 1] ?? 0;
		// [lane, start, end, opacity, color]
		const data: (string | number)[][] = [];
		names.forEach(([bid], lane) => {
			const color = BOON_COLORS[bid] ?? '#8a93a8';
			for (const r of s.boons[bid] ?? []) {
				const full = FULL[bid];
				const op = full && r[2] != null ? 0.3 + 0.7 * Math.min(r[2] / full, 1) : 0.85;
				data.push([lane, r[0], r[1], op, color]);
			}
		});
		for (const [a, b] of s.downs) data.push([names.length, a, b, 0.9, C.down]);
		for (const [a, b] of s.deaths) data.push([names.length + 1, a, b, 0.9, C.dead]);
		const rounds = timeline.mode === 'gvg' ? (timeline.rounds ?? []) : [];
		const afterCall = rounds
			.map((r, i) => [r.calloff, rounds[i + 1]?.start ?? tEnd])
			.filter(([a, b]) => b - a >= 1)
			.map(([a, b]) => [{ xAxis: a }, { xAxis: b }]);
		return {
			backgroundColor: 'transparent',
			animation: false,
			textStyle: { color: C.text, fontFamily: 'inherit' },
			tooltip: {
				trigger: 'axis',
				axisPointer: { type: 'line', lineStyle: { color: '#5d6680' } },
				backgroundColor: '#1c2335',
				borderColor: '#2c3550',
				textStyle: { color: '#e7eaf2', fontSize: 12 },
				formatter: (params: any[]) => {
					const x = pointerX() ?? params[0]?.value?.[0];
					if (x == null) return '';
					const lines = [`<b>${duration(x)}</b>`];
					if (at(s.deaths, x)) lines.push(`<span style="color:${C.dead}">✕ dead</span>`);
					else if (at(s.downs, x)) lines.push(`<span style="color:${C.down}">▲ downed</span>`);
					const on = names
						.map(([bid, name]) => {
							const r = at(s.boons[bid], x);
							if (!r) return null;
							const dot = `<span style="display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:6px;background:${BOON_COLORS[bid] ?? '#8a93a8'}"></span>`;
							return `${dot}${name}${r[2] != null ? `: <b>${r[2]}</b>` : ''}`;
						})
						.filter(Boolean);
					lines.push(...(on.length ? (on as string[]) : ['<span style="opacity:.65">no boons</span>']));
					return lines.join('<br/>');
				}
			},
			grid: { left: 96, right: 24, top: 8, bottom: 52 },
			xAxis: {
				type: 'value',
				min: 0,
				max: tEnd,
				axisLine: { lineStyle: { color: C.line } },
				axisLabel: { color: C.text, formatter: (v: number) => duration(v) },
				splitLine: { show: false }
			},
			yAxis: {
				type: 'category',
				data: lanes,
				inverse: true,
				axisLabel: { color: C.text, fontSize: 11 },
				axisLine: { show: false },
				axisTick: { show: false },
				splitLine: { show: true, lineStyle: { color: C.line } }
			},
			dataZoom: [{ type: 'inside', xAxisIndex: 0, filterMode: 'none' }],
			series: [
				{
					type: 'custom',
					data,
					encode: { x: [1, 2], y: 0 },
					silent: true,
					renderItem: (params: any, api: any) => {
						const lane = api.value(0);
						const a = api.coord([api.value(1), lane]);
						const b = api.coord([api.value(2), lane]);
						const h = api.size([0, 1])[1] * 0.62;
						const rect = graphic.clipRectByRect(
							{ x: a[0], y: a[1] - h / 2, width: Math.max(b[0] - a[0], 1), height: h },
							params.coordSys
						);
						if (!rect) return null;
						const item = data[params.dataIndex];
						return { type: 'rect', shape: rect, style: { fill: item[4] as string, opacity: item[3] as number } };
					}
				},
				// Drives the axis tooltip (custom series don't), and shades GvG call-offs.
				{
					type: 'line',
					data: t.map((x) => [x, lanes[0]]),
					showSymbol: false,
					lineStyle: { opacity: 0 },
					markArea: afterCall.length
						? { silent: true, itemStyle: { color: 'rgba(138,147,168,0.10)' }, data: afterCall }
						: undefined
				}
			]
		};
	}

	onMount(() => {
		chart = init(el, undefined, { renderer: 'canvas' });
		pointerX = trackPointer(chart);
		chart.setOption(option());
		ro = new ResizeObserver(() => chart?.resize());
		ro.observe(el);
	});

	$effect(() => {
		void series;
		void timeline;
		chart?.setOption(option(), { notMerge: true });
		chart?.resize();
	});

	onDestroy(() => {
		ro?.disconnect();
		chart?.dispose();
	});
</script>

<div bind:this={el} style="height: {height}px" class="w-full"></div>
