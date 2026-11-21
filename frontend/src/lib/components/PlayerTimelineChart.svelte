<script lang="ts">
	// One player over a fight (the Debrief timeline with a player picked): health, boons and
	// conditions; damage out / in and healing; distance to the tag and to the squad.
	import { onDestroy, onMount } from 'svelte';
	import { init, use, type EChartsType } from 'echarts/core';
	import { BarChart, LineChart } from 'echarts/charts';
	import { DataZoomComponent, GridComponent, LegendComponent, MarkAreaComponent, TooltipComponent } from 'echarts/components';
	import { CanvasRenderer } from 'echarts/renderers';
	import type { PlayerSeries, Timeline } from '#lib/api.ts';
	import { compact, duration } from '#lib/format.ts';
	import { trackPointer } from '#lib/timelineEvents.ts';

	use([LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent, MarkAreaComponent, DataZoomComponent, CanvasRenderer]);

	let {
		series,
		timeline,
		highlight = null,
		height = 460
	}: {
		series: PlayerSeries;
		timeline: Timeline;
		highlight?: [number, number] | null;
		height?: number;
	} = $props();

	let el: HTMLDivElement;
	let chart: EChartsType | null = null;
	let ro: ResizeObserver | null = null;
	let pointerX: () => number | null = () => null;

	const C = {
		text: '#8a93a8',
		line: '#222a3d',
		health: '#3ecf8e',
		boons: '#e3c34f',
		cond: '#c084fc',
		out: '#3ecf8e',
		in: '#f2555a',
		heal: '#5eead4',
		tag: '#7c9cff',
		stack: '#8a93a8',
		down: 'rgba(245,158,66,0.18)',
		dead: 'rgba(242,85,90,0.16)'
	};

	function option() {
		const s = series;
		const t = s.t;
		const tEnd = t[t.length - 1] ?? 0;
		const xy = (a: (number | null)[] | null | undefined, f = (v: number) => v) =>
			(a ?? []).map((v, i) => [t[i], v == null ? null : f(v)]);
		const states = [
			...s.downs.map(([a, b]) => [{ xAxis: a, itemStyle: { color: C.down } }, { xAxis: b }]),
			...s.deaths.map(([a, b]) => [{ xAxis: a, itemStyle: { color: C.dead } }, { xAxis: b }])
		];
		const marks = highlight
			? [[{ xAxis: highlight[0], itemStyle: { color: 'rgba(245,158,66,0.10)', borderColor: 'rgba(245,158,66,0.6)', borderWidth: 1 } }, { xAxis: highlight[1] }]]
			: [];
		const rounds = timeline.mode === 'gvg' ? (timeline.rounds ?? []) : [];
		const afterCall = rounds
			.map((r, i) => [r.calloff, rounds[i + 1]?.start ?? tEnd])
			.filter(([a, b]) => b - a >= 1)
			.map(([a, b]) => [{ xAxis: a, itemStyle: { color: 'rgba(138,147,168,0.10)' } }, { xAxis: b }]);
		const line = (name: string, data: any[], color: string, extra: object = {}) => ({
			name,
			type: 'line',
			data,
			showSymbol: false,
			lineStyle: { width: 1.5, color },
			itemStyle: { color },
			...extra
		});
		const series_: any[] = [
			line('Health', xy(s.health), C.health, {
				areaStyle: { color: 'rgba(62,207,142,0.10)' },
				lineStyle: { width: 2, color: C.health },
				markArea: { silent: true, data: [...states, ...marks, ...afterCall] }
			}),
			line('Boons', xy(s.boonCount), C.boons, { yAxisIndex: 1 }),
			line('Conditions', xy(s.conditions), C.cond, { yAxisIndex: 1 }),
			{
				name: 'Damage out',
				type: 'bar',
				xAxisIndex: 1,
				yAxisIndex: 2,
				data: xy(s.dmg_out),
				itemStyle: { color: C.out },
				barCategoryGap: '10%'
			},
			{
				name: 'Damage in',
				type: 'bar',
				xAxisIndex: 1,
				yAxisIndex: 2,
				data: xy(s.dmg_in, (v) => -v),
				itemStyle: { color: C.in },
				barGap: '-100%'
			},
			line('Heal + barrier', s.healing.map((v, i) => [t[i], (v ?? 0) + (s.barrier[i] ?? 0)]), C.heal, { xAxisIndex: 1, yAxisIndex: 2 }),
			...(s.dist_tag ? [line('Dist. to tag', xy(s.dist_tag), C.tag, { xAxisIndex: 2, yAxisIndex: 3 })] : []),
			line('Dist. to squad', xy(s.dist_stack), C.stack, { xAxisIndex: 2, yAxisIndex: 3, lineStyle: { width: 1.5, color: C.stack, type: 'dashed' } })
		];
		const xBase = { type: 'value', min: 0, max: tEnd, axisLine: { lineStyle: { color: C.line } }, splitLine: { show: false } };
		return {
			backgroundColor: 'transparent',
			animation: false,
			textStyle: { color: C.text, fontFamily: 'inherit' },
			legend: { top: 0, textStyle: { color: C.text, fontSize: 11 }, itemWidth: 14, itemHeight: 8, icon: 'roundRect' },
			tooltip: {
				trigger: 'axis',
				axisPointer: { type: 'line', link: [{ xAxisIndex: 'all' }], lineStyle: { color: '#5d6680' } },
				backgroundColor: '#1c2335',
				borderColor: '#2c3550',
				textStyle: { color: '#e7eaf2', fontSize: 12 },
				formatter: (params: any[]) => {
					if (!params.length) return '';
					const x = pointerX() ?? params[0].value?.[0] ?? params[0].axisValue;
					const lines = [`<b>${duration(x)}</b>`];
					const inRun = (runs: [number, number][]) => runs.some(([a, b]) => a <= x && x < b);
					if (inRun(s.deaths)) lines.push('<span style="color:#f2555a">✕ dead</span>');
					else if (inRun(s.downs)) lines.push('<span style="color:#f59e42">▲ downed</span>');
					for (const p of params) {
						const v = p.value?.[1];
						if (v == null) continue;
						let txt: string;
						if (p.seriesName === 'Health') txt = `${v}%`;
						else if (p.seriesName.startsWith('Damage') || p.seriesName.startsWith('Heal')) txt = `${compact(Math.abs(v))}/s`;
						else txt = String(v);
						lines.push(`${p.marker}${p.seriesName}: <b>${txt}</b>`);
					}
					return lines.join('<br/>');
				}
			},
			axisPointer: { link: [{ xAxisIndex: 'all' }] },
			grid: [
				{ left: 56, right: 48, top: 36, height: '34%' },
				{ left: 56, right: 48, top: '50%', height: '22%' },
				{ left: 56, right: 48, top: '77%', height: '14%' }
			],
			xAxis: [
				{ ...xBase, gridIndex: 0, axisLabel: { show: false } },
				{ ...xBase, gridIndex: 1, axisLabel: { show: false } },
				{ ...xBase, gridIndex: 2, axisLabel: { color: C.text, formatter: (v: number) => duration(v) } }
			],
			yAxis: [
				{ gridIndex: 0, min: 0, max: 100, axisLabel: { color: C.text, formatter: '{value}%' }, splitLine: { lineStyle: { color: C.line } } },
				{ gridIndex: 0, min: 0, position: 'right', axisLabel: { color: C.boons }, splitLine: { show: false } },
				{ gridIndex: 1, axisLabel: { color: C.text, formatter: (v: number) => compact(Math.abs(v)) }, splitLine: { lineStyle: { color: C.line } } },
				{ gridIndex: 2, min: 0, axisLabel: { color: C.text }, splitLine: { lineStyle: { color: C.line } } }
			],
			dataZoom: [{ type: 'inside', xAxisIndex: [0, 1, 2] }],
			series: series_
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
		void highlight;
		chart?.setOption(option(), { notMerge: true });
	});

	onDestroy(() => {
		ro?.disconnect();
		chart?.dispose();
	});
</script>

<div bind:this={el} style="height: {height}px" class="w-full"></div>
