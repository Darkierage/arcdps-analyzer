<script lang="ts">
	// One stat per session across all sessions, oldest to newest (the Trends page).
	import { onDestroy, onMount } from 'svelte';
	import { init, use, type EChartsType } from 'echarts/core';
	import { LineChart } from 'echarts/charts';
	import { GridComponent, TooltipComponent } from 'echarts/components';
	import { CanvasRenderer } from 'echarts/renderers';
	import type { TrendSession } from '#lib/api.ts';
	import { dateLabel, fmtValue } from '#lib/format.ts';
	import { sessionTooltipHtml, type TrendStatInfo } from '#lib/trends.ts';

	use([LineChart, GridComponent, TooltipComponent, CanvasRenderer]);

	let {
		sessions,
		stat,
		onsession,
		height = 300
	}: {
		/** Oldest first. */
		sessions: TrendSession[];
		stat: TrendStatInfo;
		onsession?: (sessionId: number) => void;
		height?: number;
	} = $props();

	let el: HTMLDivElement;
	let chart: EChartsType | null = null;
	let ro: ResizeObserver | null = null;

	const C = { text: '#8a93a8', line: '#222a3d', main: '#7c9cff' };

	function option() {
		return {
			backgroundColor: 'transparent',
			animation: false,
			textStyle: { color: C.text, fontFamily: 'inherit' },
			tooltip: {
				trigger: 'axis',
				backgroundColor: '#1c2335',
				borderColor: '#2c3550',
				textStyle: { color: '#e7eaf2', fontSize: 12 },
				// Escaped in sessionTooltipHtml: a session's name is typed by the user.
				formatter: (params: any[]) => {
					const s = sessions[params[0]?.dataIndex ?? -1];
					return s ? sessionTooltipHtml(s, stat) : '';
				}
			},
			grid: { left: 56, right: 24, top: 16, bottom: 32 },
			xAxis: {
				type: 'category',
				// Two sessions on one day get the same label; the index keeps them apart.
				data: sessions.map((s) => dateLabel(s.start)),
				axisLine: { lineStyle: { color: C.line } },
				axisLabel: { color: C.text, hideOverlap: true }
			},
			yAxis: {
				type: 'value',
				min: 0,
				max: stat.key === 'winRate' ? 100 : undefined,
				axisLabel: { color: C.text, formatter: (v: number) => fmtValue(v, stat.fmt) },
				splitLine: { lineStyle: { color: C.line } }
			},
			series: [
				{
					name: stat.label,
					type: 'line',
					data: sessions.map((s) => s[stat.key]),
					connectNulls: false,
					symbol: 'circle',
					symbolSize: 9,
					lineStyle: { width: 2, color: C.main },
					itemStyle: { color: C.main }
				}
			]
		};
	}

	onMount(() => {
		chart = init(el, undefined, { renderer: 'canvas' });
		chart.setOption(option());
		// A click anywhere over a session's column opens it (the points alone are small).
		chart.getZr().on('click', (e) => {
			if (!chart || !chart.containPixel('grid', [e.offsetX, e.offsetY])) return;
			const [i] = chart.convertFromPixel({ seriesIndex: 0 }, [e.offsetX, e.offsetY]) as number[];
			const s = sessions[Math.round(i)];
			if (s) onsession?.(s.id);
		});
		ro = new ResizeObserver(() => chart?.resize());
		ro.observe(el);
	});

	$effect(() => {
		void sessions;
		void stat;
		chart?.setOption(option(), { notMerge: true });
	});

	onDestroy(() => {
		ro?.disconnect();
		chart?.dispose();
	});
</script>

<div bind:this={el} style="height: {height}px" class="w-full cursor-pointer"></div>
