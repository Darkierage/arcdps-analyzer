<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { init, use, type EChartsType } from 'echarts/core';
	import { BarChart, LineChart, ScatterChart } from 'echarts/charts';
	import {
		DataZoomComponent,
		GridComponent,
		LegendComponent,
		MarkAreaComponent,
		TooltipComponent
	} from 'echarts/components';
	import { CanvasRenderer } from 'echarts/renderers';
	import type { Timeline } from '#lib/api.ts';
	import { compact, duration } from '#lib/format.ts';

	use([
		LineChart,
		BarChart,
		ScatterChart,
		GridComponent,
		TooltipComponent,
		LegendComponent,
		MarkAreaComponent,
		DataZoomComponent,
		CanvasRenderer
	]);

	let {
		timeline,
		highlight = null,
		partyLines = false,
		height = 420
	}: {
		timeline: Timeline;
		highlight?: [number, number] | null;
		partyLines?: boolean;
		height?: number;
	} = $props();

	let el: HTMLDivElement;
	let chart: EChartsType | null = null;
	let ro: ResizeObserver | null = null;

	const C = {
		text: '#8a93a8',
		line: '#222a3d',
		stab: '#7c9cff',
		resist: '#c084fc',
		prot: '#38bdf8',
		boons: '#e3c34f',
		out: '#3ecf8e',
		in: '#f2555a',
		heal: '#5eead4',
		down: '#f59e42',
		dead: '#f2555a',
		enemy: '#3ecf8e'
	};
	const partyPalette = ['#7c9cff', '#f59e42', '#3ecf8e', '#c084fc', '#38bdf8', '#f472b6', '#e3c34f', '#a3e635', '#fb7185', '#2dd4bf'];

	function pct(a: (number | null)[] | undefined) {
		return (a ?? []).map((v) => (v == null ? null : Math.round(v * 1000) / 10));
	}

	function option() {
		const tl = timeline;
		const t = tl.t;
		const sq = tl.squad;
		const lane = (color: string) => ({ itemStyle: { color }, symbolSize: 9, yAxisIndex: 2, xAxisIndex: 2 });
		const series: any[] = [
			{
				name: 'Stability',
				type: 'line',
				data: pct(sq.stab).map((v, i) => [t[i], v]),
				showSymbol: false,
				lineStyle: { width: 2, color: C.stab },
				itemStyle: { color: C.stab },
				areaStyle: { color: 'rgba(124,156,255,0.12)' },
				markArea: highlight
					? {
							silent: true,
							itemStyle: { color: 'rgba(245,158,66,0.14)', borderColor: 'rgba(245,158,66,0.6)', borderWidth: 1 },
							data: [[{ xAxis: highlight[0] }, { xAxis: highlight[1] }]]
						}
					: undefined
			},
			{
				name: 'Resistance',
				type: 'line',
				data: pct(sq.resist).map((v, i) => [t[i], v]),
				showSymbol: false,
				lineStyle: { width: 1.5, color: C.resist },
				itemStyle: { color: C.resist }
			},
			{
				name: 'Protection',
				type: 'line',
				data: pct(sq.prot).map((v, i) => [t[i], v]),
				showSymbol: false,
				lineStyle: { width: 1.5, color: C.prot, type: 'dashed' },
				itemStyle: { color: C.prot }
			},
			{
				name: 'Avg boons',
				type: 'line',
				yAxisIndex: 1,
				data: (sq.boons ?? []).map((v, i) => [t[i], v == null ? null : Math.round(v * 10) / 10]),
				showSymbol: false,
				lineStyle: { width: 1.5, color: C.boons },
				itemStyle: { color: C.boons }
			},
			{
				name: 'Damage out',
				type: 'bar',
				xAxisIndex: 1,
				yAxisIndex: 3,
				data: (sq.dmg_out ?? []).map((v, i) => [t[i], v]),
				itemStyle: { color: C.out },
				barCategoryGap: '10%'
			},
			{
				name: 'Damage in',
				type: 'bar',
				xAxisIndex: 1,
				yAxisIndex: 3,
				data: (sq.dmg_in ?? []).map((v, i) => [t[i], v == null ? null : -v]),
				itemStyle: { color: C.in },
				barGap: '-100%'
			},
			{
				name: 'Heal + barrier',
				type: 'line',
				xAxisIndex: 1,
				yAxisIndex: 3,
				data: (sq.healing ?? []).map((v, i) => [t[i], (v ?? 0) + (sq.barrier?.[i] ?? 0)]),
				showSymbol: false,
				lineStyle: { width: 1.5, color: C.heal },
				itemStyle: { color: C.heal }
			},
			{
				name: 'Squad down',
				type: 'scatter',
				...lane(C.down),
				symbol: 'triangle',
				data: tl.squadDowns.map((d) => ({ value: [d.t, 1], d })),
				symbolSize: 9
			},
			{
				name: 'Squad death',
				type: 'scatter',
				...lane(C.dead),
				symbol: 'path://M2 2 L10 10 M10 2 L2 10',
				itemStyle: { color: C.dead, borderColor: C.dead, borderWidth: 2.5 },
				data: tl.squadDeaths.map((d) => ({ value: [d.t, 1], d })),
				symbolSize: 8
			},
			{
				name: 'Enemy down',
				type: 'scatter',
				...lane('#a7f3d0'),
				symbol: 'triangle',
				data: tl.enemyDowns.map((x) => [x, 0]),
				symbolSize: 8
			},
			{
				name: 'Enemy death',
				type: 'scatter',
				...lane(C.enemy),
				symbol: 'circle',
				data: tl.enemyDeaths.map((x) => [x, 0]),
				symbolSize: 7
			}
		];
		if (partyLines) {
			Object.entries(tl.parties).forEach(([g, s], i) => {
				series.push({
					name: `Party ${g} stab`,
					type: 'line',
					data: pct(s.stab).map((v, j) => [t[j], v]),
					showSymbol: false,
					lineStyle: { width: 1, color: partyPalette[i % partyPalette.length], opacity: 0.8 },
					itemStyle: { color: partyPalette[i % partyPalette.length] }
				});
			});
		}
		const xBase = { type: 'value', min: 0, max: t[t.length - 1] ?? 0, axisLine: { lineStyle: { color: C.line } } };
		return {
			backgroundColor: 'transparent',
			animation: false,
			textStyle: { color: C.text, fontFamily: 'inherit' },
			legend: {
				top: 0,
				textStyle: { color: C.text, fontSize: 11 },
				itemWidth: 14,
				itemHeight: 8,
				icon: 'roundRect',
				selected: Object.fromEntries(
					Object.keys(tl.parties).map((g) => [`Party ${g} stab`, true])
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
					for (const p of params) {
						const v = p.value?.[1];
						if (v == null || p.seriesType === 'scatter') continue;
						let txt: string;
						if (p.seriesName.includes('Damage') || p.seriesName.includes('Heal')) txt = compact(Math.abs(v)) + '/s';
						else if (p.seriesName === 'Avg boons') txt = String(v);
						else txt = v + '%';
						lines.push(`${p.marker}${p.seriesName}: <b>${txt}</b>`);
					}
					return lines.join('<br/>');
				}
			},
			axisPointer: { link: [{ xAxisIndex: 'all' }] },
			grid: [
				{ left: 48, right: 48, top: 36, height: '42%' },
				{ left: 48, right: 48, top: '58%', height: '22%' },
				{ left: 48, right: 48, top: '85%', height: '7%' }
			],
			xAxis: [
				{ ...xBase, gridIndex: 0, axisLabel: { show: false }, splitLine: { show: false } },
				{ ...xBase, gridIndex: 1, axisLabel: { show: false }, splitLine: { show: false } },
				{
					...xBase,
					gridIndex: 2,
					axisLabel: { color: C.text, formatter: (v: number) => duration(v) },
					splitLine: { show: false }
				}
			],
			yAxis: [
				{
					gridIndex: 0,
					min: 0,
					max: 100,
					axisLabel: { color: C.text, formatter: '{value}%' },
					splitLine: { lineStyle: { color: C.line } }
				},
				{ gridIndex: 0, min: 0, position: 'right', axisLabel: { color: C.boons }, splitLine: { show: false } },
				{
					gridIndex: 2,
					type: 'category',
					data: ['Enemy', 'Squad'],
					axisLabel: { color: C.text, fontSize: 10 },
					axisLine: { show: false },
					axisTick: { show: false }
				},
				{
					gridIndex: 1,
					axisLabel: { color: C.text, formatter: (v: number) => compact(Math.abs(v)) },
					splitLine: { lineStyle: { color: C.line } }
				}
			],
			dataZoom: [{ type: 'inside', xAxisIndex: [0, 1, 2] }],
			series
		};
	}

	onMount(() => {
		chart = init(el, undefined, { renderer: 'canvas' });
		chart.setOption(option());
		ro = new ResizeObserver(() => chart?.resize());
		ro.observe(el);
	});

	$effect(() => {
		// Re-render when inputs change.
		void highlight;
		void partyLines;
		void timeline;
		chart?.setOption(option(), { notMerge: true });
	});

	onDestroy(() => {
		ro?.disconnect();
		chart?.dispose();
	});
</script>

<div bind:this={el} style="height: {height}px" class="w-full"></div>
