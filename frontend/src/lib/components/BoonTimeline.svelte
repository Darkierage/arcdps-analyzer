<script lang="ts">
	// Boons over time for the squad or one party (the fight page's Boons tab).
	import { onDestroy, onMount } from 'svelte';
	import { init, use, type EChartsType } from 'echarts/core';
	import { LineChart, ScatterChart } from 'echarts/charts';
	import { DataZoomComponent, GridComponent, LegendComponent, MarkAreaComponent, TooltipComponent } from 'echarts/components';
	import { CanvasRenderer } from 'echarts/renderers';
	import type { Timeline } from '#lib/api.ts';
	import { duration } from '#lib/format.ts';

	use([LineChart, ScatterChart, GridComponent, TooltipComponent, LegendComponent, MarkAreaComponent, DataZoomComponent, CanvasRenderer]);

	let { timeline, party = 'squad', height = 380 }: { timeline: Timeline; party?: string; height?: number } = $props();

	let el: HTMLDivElement;
	let chart: EChartsType | null = null;
	let ro: ResizeObserver | null = null;

	const C = { text: '#8a93a8', line: '#222a3d', down: '#f59e42', dead: '#f2555a' };
	// EI buff id -> line color. Ids without an entry fall back to gray.
	const COLORS: Record<string, string> = {
		'1122': '#7c9cff', // Stability
		'743': '#facc15', // Aegis
		'717': '#38bdf8', // Protection
		'873': '#fb923c', // Resolution
		'26980': '#c084fc', // Resistance
		'1187': '#f472b6', // Quickness
		'30328': '#2dd4bf', // Alacrity
		'740': '#f87171', // Might
		'725': '#fda4af', // Fury
		'718': '#4ade80', // Regeneration
		'726': '#a3e635', // Vigor
		'719': '#94a3b8', // Swiftness
		'5974': '#e2e8f0' // Superspeed
	};
	// Shown at first; the rest can be switched on in the legend.
	const DEFAULT_ON = new Set(['Stability', 'Aegis', 'Protection', 'Resistance', 'Quickness', 'Alacrity', 'Might stacks']);
	const STACKS = { '1122': 'Stability stacks', '740': 'Might stacks' } as Record<string, string>;
	// Legend choices survive switching parties.
	let selected: Record<string, boolean> = {};

	function option() {
		const tl = timeline;
		const t = tl.t;
		const src = tl.boons?.[party] ?? {};
		const names = tl.boonNames ?? [];
		const mine = (d: { group: number }) => party === 'squad' || String(d.group) === party;
		const tEnd = t[t.length - 1] ?? 0;
		const rounds = tl.mode === 'gvg' ? (tl.rounds ?? []) : [];
		const afterCall = rounds
			.map((r, i) => [r.calloff, rounds[i + 1]?.start ?? tEnd])
			.filter(([a, b]) => b - a >= 1)
			.map(([a, b]) => [{ xAxis: a }, { xAxis: b }]);
		const series: any[] = [];
		for (const [bid, name] of names) {
			const color = COLORS[bid] ?? '#8a93a8';
			series.push({
				name,
				type: 'line',
				data: (src[bid] ?? []).map((v, i) => [t[i], v]),
				showSymbol: false,
				lineStyle: { width: 1.5, color },
				itemStyle: { color }
			});
			if (STACKS[bid]) {
				series.push({
					name: STACKS[bid],
					type: 'line',
					yAxisIndex: 1,
					data: (src[`${bid}s`] ?? []).map((v, i) => [t[i], v]),
					showSymbol: false,
					lineStyle: { width: 1.5, color, type: 'dashed' },
					itemStyle: { color }
				});
			}
		}
		const lane = (color: string) => ({ itemStyle: { color }, symbolSize: 9, xAxisIndex: 1, yAxisIndex: 2 });
		series.push(
			{
				name: 'Down',
				type: 'scatter',
				...lane(C.down),
				symbol: 'triangle',
				data: tl.squadDowns.filter((d) => mine(d) && !d.left).map((d) => ({ value: [d.t, 0], d }))
			},
			...(rounds.length
				? [
						{
							name: 'Left at call-off',
							type: 'scatter',
							...lane(C.down),
							symbol: 'triangle',
							itemStyle: { color: 'transparent', borderColor: C.down, borderWidth: 1.5 },
							data: tl.squadDowns.filter((d) => mine(d) && d.left).map((d) => ({ value: [d.t, 0], d }))
						}
					]
				: []),
			{
				name: 'Death',
				type: 'scatter',
				...lane(C.dead),
				symbol: 'path://M2 2 L10 10 M10 2 L2 10',
				itemStyle: { color: C.dead, borderColor: C.dead, borderWidth: 2.5 },
				symbolSize: 8,
				data: tl.squadDeaths.filter(mine).map((d) => ({ value: [d.t, 0], d }))
			}
		);
		const legendNames = series.map((s) => s.name);
		// GvG call-offs on a series of their own, so hiding a boon never hides the shading.
		if (afterCall.length) {
			series.push({
				name: 'call-offs',
				type: 'line',
				data: [],
				silent: true,
				markArea: { silent: true, itemStyle: { color: 'rgba(138,147,168,0.10)' }, data: afterCall }
			});
		}
		const xBase = { type: 'value', min: 0, max: tEnd, axisLine: { lineStyle: { color: C.line } } };
		return {
			backgroundColor: 'transparent',
			animation: false,
			textStyle: { color: C.text, fontFamily: 'inherit' },
			legend: {
				data: legendNames,
				top: 0,
				textStyle: { color: C.text, fontSize: 11 },
				itemWidth: 14,
				itemHeight: 8,
				icon: 'roundRect',
				selected: Object.fromEntries(
					legendNames.map((n) => [n, selected[n] ?? (DEFAULT_ON.has(n) || ['Down', 'Left at call-off', 'Death'].includes(n))])
				)
			},
			tooltip: {
				trigger: 'axis',
				axisPointer: { type: 'line', link: [{ xAxisIndex: 'all' }], lineStyle: { color: '#5d6680' } },
				backgroundColor: '#1c2335',
				borderColor: '#2c3550',
				textStyle: { color: '#e7eaf2', fontSize: 12 },
				formatter: (params: any[]) => {
					if (!params.length) return '';
					const x = params[0].value?.[0] ?? params[0].axisValue;
					const lines = [`<b>${duration(x)}</b>`];
					// Boons by coverage (highest first), then the stack counts.
					const rows = params.filter((p) => p.value?.[1] != null && p.seriesType !== 'scatter');
					const isStacks = (p: any) => p.seriesName.endsWith('stacks');
					rows.sort((a, b) => Number(isStacks(a)) - Number(isStacks(b)) || b.value[1] - a.value[1]);
					for (const p of rows) {
						lines.push(`${p.marker}${p.seriesName}: <b>${isStacks(p) ? p.value[1] : p.value[1] + '%'}</b>`);
					}
					return lines.join('<br/>');
				}
			},
			axisPointer: { link: [{ xAxisIndex: 'all' }] },
			grid: [
				{ left: 48, right: 48, top: 56, bottom: 64 },
				{ left: 48, right: 48, height: 22, bottom: 22 }
			],
			xAxis: [
				{ ...xBase, gridIndex: 0, axisLabel: { show: false }, splitLine: { show: false } },
				{ ...xBase, gridIndex: 1, axisLabel: { color: C.text, formatter: (v: number) => duration(v) }, splitLine: { show: false } }
			],
			yAxis: [
				{ gridIndex: 0, min: 0, max: 100, axisLabel: { color: C.text, formatter: '{value}%' }, splitLine: { lineStyle: { color: C.line } } },
				{ gridIndex: 0, min: 0, max: 25, position: 'right', name: 'stacks', nameTextStyle: { color: C.text, fontSize: 10 }, axisLabel: { color: C.text }, splitLine: { show: false } },
				{
					gridIndex: 1,
					type: 'category',
					data: [party === 'squad' ? 'Squad' : `Party ${party}`],
					axisLabel: { color: C.text, fontSize: 10 },
					axisLine: { show: false },
					axisTick: { show: false }
				}
			],
			dataZoom: [{ type: 'inside', xAxisIndex: [0, 1] }],
			series
		};
	}

	onMount(() => {
		chart = init(el, undefined, { renderer: 'canvas' });
		chart.on('legendselectchanged', (e: any) => (selected = { ...e.selected }));
		chart.setOption(option());
		ro = new ResizeObserver(() => chart?.resize());
		ro.observe(el);
	});

	$effect(() => {
		void party;
		void timeline;
		chart?.setOption(option(), { notMerge: true });
	});

	onDestroy(() => {
		ro?.disconnect();
		chart?.dispose();
	});
</script>

<div bind:this={el} style="height: {height}px" class="w-full"></div>
