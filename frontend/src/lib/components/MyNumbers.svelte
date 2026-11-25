<script lang="ts">
	import type { MyNumber } from '#lib/api.ts';
	import { compare, fmtNumber, trendClass, trendLabel } from '#lib/myplay.ts';

	/** You, your peers (same spec and job) and the squad, weighted by your time in each fight. */
	let { numbers, showTrend = false }: { numbers: MyNumber[]; showTrend?: boolean } = $props();
	const cls = (c: 'better' | 'worse' | null) => (c === 'better' ? 'text-win' : c === 'worse' ? 'text-loss' : '');
</script>

<div class="overflow-x-auto">
	<table class="w-full text-sm">
		<thead class="text-left text-xs text-faint">
			<tr>
				<th class="py-1.5 pr-3 font-medium"></th>
				<th class="px-3 py-1.5 text-right font-medium">You</th>
				<th class="px-3 py-1.5 text-right font-medium" title="Other players with your spec and job in the same fights">Peers</th>
				<th class="px-3 py-1.5 text-right font-medium" title="Median of the squad in the same fights">Squad</th>
				{#if showTrend}<th class="py-1.5 pl-3 font-medium">Trend</th>{/if}
			</tr>
		</thead>
		<tbody>
			{#each numbers as n (n.key)}
				{@const ref = n.peers ?? n.squad}
				<tr class="border-t border-line">
					<td class="py-1.5 pr-3 text-muted">{n.label}</td>
					<td class="tabular px-3 py-1.5 text-right font-medium {cls(compare(n.you, ref, n.higherIsBetter))}">{fmtNumber(n.you, n)}</td>
					<td class="tabular px-3 py-1.5 text-right text-muted" title={n.peerFights ? `${n.peerFights} fight${n.peerFights === 1 ? '' : 's'} with peers` : 'No player with your spec and job in these fights'}>
						{fmtNumber(n.peers, n)}
					</td>
					<td class="tabular px-3 py-1.5 text-right text-muted">{fmtNumber(n.squad, n)}</td>
					{#if showTrend}<td class="py-1.5 pl-3 text-xs {n.trend ? trendClass[n.trend] : 'text-faint'}">{n.trend ? trendLabel[n.trend] : ''}</td>{/if}
				</tr>
			{/each}
		</tbody>
	</table>
</div>
