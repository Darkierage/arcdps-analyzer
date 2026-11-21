<script lang="ts">
	// One stat per fight over a session, for the squad, a party or a player (session Summary).
	import { onDestroy, onMount } from 'svelte';
	import { init, use, type EChartsType } from 'echarts/core';
	import { LineChart } from 'echarts/charts';
	import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components';
	import { CanvasRenderer } from 'echarts/renderers';
	import type { Column, SessionAggregate } from '#lib/api.ts';
	import { fmtValue, timeOfDay } from '#lib/format.ts';
	import { RESULT_COLORS as RESULT, trendTooltipHtml } from '#lib/trendTooltip.ts';

	use([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer]);

	let {
		fights,
		values,
		reference = null,
		label,
		referenceLabel = '',
		fmt,
		present = null,
		missingLabel = 'no value',
		onfight,
		height = 300
	}: {
		fights: SessionAggregate['fights'];
		/** One value per fight; null where the squad / party / player wasn't in it. */
		values: (number | null)[];
		/** A faint comparison line (the average player when showing one player). */
		reference?: (number | null)[] | null;
		label: string;
		referenceLabel?: string;
		fmt: Column['fmt'];
		/** Per fight: was the squad / party / player in it? A missing value in a fight they were
		 * in reads `missingLabel` instead of "not in this fight". */
		present?: boolean[] | null;
		missingLabel?: string;
		onfight?: (fightId: number) => void;
		height?: number;
	} = $props();

	let el: HTMLDivElement;
	let chart: EChartsType | null = null;
	let ro: ResizeObserver | null = null;

	const C = { text: '#8a93a8', line: '#222a3d', main: '#7c9cff', ref: '#5d6680' };

	function option() {
		const cats = fights.map((f) => timeOfDay(f.start));
		const series: any[] = [
			{
				name: label,
				type: 'line',
				data: values.map((v, i) => ({ value: v, itemStyle: { color: RESULT[fights[i]?.result] ?? C.main } })),
				connectNulls: false,
				symbol: 'circle',
				symbolSize: 9,
				lineStyle: { width: 2, color: C.main },
				itemStyle: { color: C.main }
			}
		];
		if (reference) {
			series.push({
				name: referenceLabel,
				type: 'line',
				data: reference,
				symbol: 'none',
				lineStyle: { width: 1.5, color: C.ref, type: 'dashed' },
				itemStyle: { color: C.ref },
				silent: true
			});
		}
		return {
			backgroundColor: 'transparent',
			animation: false,
			textStyle: { color: C.text, fontFamily: 'inherit' },
			legend: { top: 0, textStyle: { color: C.text, fontSize: 11 }, itemWidth: 14, itemHeight: 8 },
			tooltip: {
				trigger: 'axis',
				backgroundColor: '#1c2335',
				borderColor: '#2c3550',
				textStyle: { color: '#e7eaf2', fontSize: 12 },
				formatter: (params: any[]) => {
					const i = params[0]?.dataIndex ?? 0;
					const f = fights[i];
					if (!f) return '';
					// Escaped: the series name holds a player's name from the log.
					const lines = params.map((p) => ({
						marker: p.marker,
						name: p.seriesName,
						value: p.value?.value !== undefined ? p.value.value : p.value,
						missing: present?.[i] ? missingLabel : undefined
					}));
					return trendTooltipHtml(f, lines, fmt);
				}
			},
			grid: { left: 56, right: 24, top: 36, bottom: 32 },
			xAxis: {
				type: 'category',
				data: cats,
				axisLine: { lineStyle: { color: C.line } },
				axisLabel: { color: C.text, hideOverlap: true }
			},
			yAxis: {
				type: 'value',
				min: 0,
				axisLabel: { color: C.text, formatter: (v: number) => fmtValue(v, fmt) },
				splitLine: { lineStyle: { color: C.line } }
			},
			series
		};
	}

	onMount(() => {
		chart = init(el, undefined, { renderer: 'canvas' });
		chart.setOption(option());
		// A click anywhere over a fight's column opens it (the points alone are small).
		chart.getZr().on('click', (e) => {
			if (!chart) return;
			const [i] = chart.convertFromPixel({ seriesIndex: 0 }, [e.offsetX, e.offsetY]) as number[];
			const f = fights[Math.round(i)];
			if (f && chart.containPixel('grid', [e.offsetX, e.offsetY])) onfight?.(f.id);
		});
		ro = new ResizeObserver(() => chart?.resize());
		ro.observe(el);
	});

	$effect(() => {
		void values;
		void reference;
		void present;
		void missingLabel;
		void label;
		void fmt;
		chart?.setOption(option(), { notMerge: true });
	});

	onDestroy(() => {
		ro?.disconnect();
		chart?.dispose();
	});
</script>

<div bind:this={el} style="height: {height}px" class="w-full cursor-pointer"></div>
