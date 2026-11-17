<script lang="ts">
	import type { FightRow } from '#lib/api.ts';
	import { compact, dateLabel, duration, timeOfDay } from '#lib/format.ts';
	import Badge, { severityBar } from './Badges.svelte';

	let { fights, showDate = true }: { fights: FightRow[]; showDate?: boolean } = $props();
</script>

<div class="card overflow-hidden">
	<table class="w-full text-sm">
		<thead>
			<tr class="border-b border-line text-left text-xs text-muted">
				<th class="px-4 py-2.5 font-medium">Time</th>
				<th class="px-3 py-2.5 font-medium">Map</th>
				<th class="px-3 py-2.5 text-right font-medium">Length</th>
				<th class="px-3 py-2.5 text-right font-medium">Squad vs enemy</th>
				<th class="px-3 py-2.5 text-right font-medium">Kills / deaths</th>
				<th class="px-3 py-2.5 text-right font-medium">Damage</th>
				<th class="px-3 py-2.5 font-medium">Result</th>
				<th class="px-3 py-2.5 font-medium">Top issue</th>
			</tr>
		</thead>
		<tbody>
			{#each fights as f (f.id)}
				{@const s = f.summary}
				<tr class="group border-b border-line/60 transition last:border-0 hover:bg-panel-2 {f.status === 'skipped' ? 'opacity-50' : ''}">
					<td class="px-4 py-2.5 whitespace-nowrap">
						<a href="/fights/{f.id}" class="block">
							<div class="tabular font-medium">{timeOfDay(s?.start ?? f.fight_start)}</div>
							{#if showDate}<div class="text-xs text-faint">{dateLabel(s?.start ?? f.fight_start) || f.log_name}</div>{/if}
						</a>
					</td>
					<td class="px-3 py-2.5 text-muted"><a href="/fights/{f.id}" class="block">{s?.map ?? f.log_name}</a></td>
					<td class="tabular px-3 py-2.5 text-right text-muted">{duration(s?.durationS)}</td>
					<td class="tabular px-3 py-2.5 text-right">
						{#if s?.squadCount != null}
							<span class="text-text">{s.squadInFight ?? s.squadCount}</span>{#if s.allyCount}<span class="text-faint">+{s.allyCount}</span>{/if}
							<span class="text-faint">vs</span>
							<span class="{(s.outnumberRatio ?? 0) >= 1.3 ? 'text-major' : 'text-text'}">{s.enemyCount}</span>
						{:else}–{/if}
					</td>
					<td class="tabular px-3 py-2.5 text-right">
						{#if s?.enemyDeaths != null}
							<span class="text-win">{s.enemyDeaths}</span>
							<span class="text-faint">/</span>
							<span class="text-loss">{s.squadDeaths}</span>
						{:else}–{/if}
					</td>
					<td class="tabular px-3 py-2.5 text-right text-muted">{compact(s?.squadDamage)}</td>
					<td class="px-3 py-2.5">
						{#if f.status === 'done' && f.result}
							<Badge result={f.result} />
						{:else}
							<Badge status={f.status} />
						{/if}
					</td>
					<td class="max-w-[22rem] px-3 py-2.5">
						{#if f.status === 'done' && s?.topIssue}
							<a href="/fights/{f.id}" class="flex items-center gap-2 truncate text-muted group-hover:text-text">
								<span class="h-3.5 w-1 shrink-0 rounded-full {severityBar[s.topSeverity ?? 'minor']}"></span>
								<span class="truncate">{s.topIssue}</span>
							</a>
						{:else if f.status === 'skipped' || f.status === 'failed'}
							<span class="block truncate text-xs text-faint" title={f.error ?? ''}>{f.error}</span>
						{/if}
					</td>
				</tr>
			{/each}
		</tbody>
	</table>
</div>
