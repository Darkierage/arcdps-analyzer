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
	import { eventsSection, playheadX, secondsPerPixels, trackClicks, trackPointer } from '#lib/timelineEvents.ts';

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

	// party: 'squad', a party's group number (its own boons, damage and downs), or 'all'
	// (the squad chart plus one stability line per party).
	let {
		timeline,
		highlight = null,
		party = 'squad',
		professions = {},
		height = 420,
		onseek,
		playhead = null
	}: {
		timeline: Timeline;
		highlight?: [number, number] | null;
		party?: string;
		/** Player name -> profession, for the death lines in the tooltip. */
		professions?: Record<string, string>;
		height?: number;
		/** Click on the chart: the fight second clicked (the replay jumps there). */
		onseek?: (t: number) => void;
		/** Fight second to mark with a vertical line (the replay's position). */
		playhead?: number | null;
	} = $props();

	let el: HTMLDivElement;
	let chart: EChartsType | null = null;
	let ro: ResizeObserver | null = null;
	let pointerX: () => number | null = () => null;
	// Legend items switched off since the last render (a re-render resets the legend).
	let legend: Record<string, boolean> = {};

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
		const one = party !== 'squad' && party !== 'all' && tl.parties[party] ? party : null;
		const sq = one ? tl.parties[one] : tl.squad;
		const who = one ? `Party ${one}` : 'Squad';
		const mine = (d: { group: number }) => !one || String(d.group) === one;
		const lane = (color: string) => ({ itemStyle: { color }, symbolSize: 9, yAxisIndex: 2, xAxisIndex: 2 });
		// GvG: shade what follows each call-off (regroup / rezzing; not part of the fight).
		const tEnd = t[t.length - 1] ?? 0;
		const rounds = tl.mode === 'gvg' ? (tl.rounds ?? []) : [];
		const afterCall = rounds
			.map((r, i) => [r.calloff, rounds[i + 1]?.start ?? tEnd])
			.filter(([a, b]) => b - a >= 1)
			.map(([a, b], i) => [
				{ xAxis: a, name: rounds.length > 1 ? `Round ${i + 1} called` : 'Called off' },
				{ xAxis: b }
			]);
		const enemyLeft = new Set(tl.enemyDownsLeft ?? []);
		const hollow = (color: string) => ({ color: 'transparent', borderColor: color, borderWidth: 1.5 });
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
				barCategoryGap: '10%',
				markArea: afterCall.length
					? {
							silent: true,
							itemStyle: { color: 'rgba(138,147,168,0.10)' },
							label: { color: C.text, fontSize: 10, position: 'insideTopLeft' },
							data: afterCall
						}
					: undefined
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
				name: `${who} down`,
				type: 'scatter',
				...lane(C.down),
				symbol: 'triangle',
				data: tl.squadDowns.filter((d) => !d.left && mine(d)).map((d) => ({ value: [d.t, 1], d })),
				symbolSize: 9
			},
			...(rounds.length
				? [
						{
							name: 'Left at call-off',
							type: 'scatter',
							...lane(C.down),
							symbol: 'triangle',
							itemStyle: hollow(C.down),
							data: tl.squadDowns.filter((d) => d.left && mine(d)).map((d) => ({ value: [d.t, 1], d })),
							symbolSize: 9
						},
						{
							name: 'Enemy left at call-off',
							type: 'scatter',
							...lane('#a7f3d0'),
							symbol: 'triangle',
							itemStyle: hollow('#a7f3d0'),
							data: tl.enemyDowns.filter((x) => enemyLeft.has(Math.round(x * 100) / 100)).map((x) => [x, 0]),
							symbolSize: 8
						}
					]
				: []),
			{
				name: `${who} death`,
				type: 'scatter',
				...lane(C.dead),
				symbol: 'path://M2 2 L10 10 M10 2 L2 10',
				itemStyle: { color: C.dead, borderColor: C.dead, borderWidth: 2.5 },
				data: tl.squadDeaths.filter(mine).map((d) => ({ value: [d.t, 1], d })),
				symbolSize: 8
			},
			{
				name: 'Enemy down',
				type: 'scatter',
				...lane('#a7f3d0'),
				symbol: 'triangle',
				data: tl.enemyDowns.filter((x) => !enemyLeft.has(Math.round(x * 100) / 100)).map((x) => [x, 0]),
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
		if (party === 'all') {
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
					const x = pointerX() ?? params[0].value?.[0] ?? params[0].axisValue;
					const lines = [`<b>${duration(x)}</b>`];
					// Who went down or died under the pointer (the markers alone only show when).
					const shown = (name: string) => legend[name] !== false;
					const events = eventsSection(tl, x, secondsPerPixels(chart, x), {
						group: one,
						enemies: true,
						professions,
						shown: {
							downs: shown(`${who} down`),
							leftDowns: shown('Left at call-off'),
							deaths: shown(`${who} death`),
							enemyDowns: shown('Enemy down'),
							enemyDeaths: shown('Enemy death')
						}
					});
					for (const p of params) {
						const v = p.value?.[1];
						if (v == null || p.seriesType === 'scatter') continue;
						let txt: string;
						if (p.seriesName.includes('Damage') || p.seriesName.includes('Heal')) txt = compact(Math.abs(v)) + '/s';
						else if (p.seriesName === 'Avg boons') txt = String(v);
						else txt = v + '%';
						lines.push(`${p.marker}${p.seriesName}: <b>${txt}</b>`);
					}
					return lines.join('<br/>') + events;
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
					data: ['Enemy', who],
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
		pointerX = trackPointer(chart);
		trackClicks(chart, () => onseek);
		chart.on('datazoom', () => {
			zoomed++;
		});
		chart.on('legendselectchanged', (e: any) => (legend = { ...e.selected }));
		chart.setOption(option());
		ro = new ResizeObserver(() => {
			chart?.resize();
			zoomed++; // the playhead moves with the axis
		});
		ro.observe(el);
	});

	$effect(() => {
		// Re-render when inputs change.
		void highlight;
		void party;
		void timeline;
		legend = {};
		chart?.setOption(option(), { notMerge: true });
	});

	// The playhead is a line over the chart, moved without re-rendering the chart (it changes
	// every frame while the replay plays).
	let zoomed = $state(0);
	const headX = $derived.by(() => {
		void zoomed;
		return playheadX(chart, playhead, 40);
	});

	onDestroy(() => {
		ro?.disconnect();
		chart?.dispose();
	});
</script>

<div class="relative w-full">
	<div bind:this={el} style="height: {height}px" class="w-full {onseek ? 'cursor-pointer' : ''}"></div>
	{#if headX != null}
		<div class="pointer-events-none absolute top-6 bottom-2 w-0.5 -translate-x-1/2 rounded bg-white shadow-[0_0_4px_rgba(0,0,0,0.8)]" style="left: {headX}px"></div>
	{/if}
</div>
