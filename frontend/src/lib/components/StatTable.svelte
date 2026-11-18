<script lang="ts">
	import type { Column, Row } from '#lib/api.ts';
	import { fmtValue, profColor } from '#lib/format.ts';

	let {
		columns,
		players,
		parties = [],
		squad = null,
		mode = 'player',
		hideAbsent = true,
		extraLead = null,
		rowHref = null
	}: {
		columns: Column[];
		players: Row[];
		parties?: Row[];
		squad?: Row | null;
		mode?: 'player' | 'party';
		hideAbsent?: boolean;
		extraLead?: { key: string; label: string } | null;
		rowHref?: ((r: Row) => string) | null;
	} = $props();

	let sortKey = $state<string | null>(null);
	let sortDir = $state<1 | -1>(-1);

	const baseRows = $derived(
		mode === 'party' ? parties : players.filter((r) => !hideAbsent || r.in_fight !== false)
	);

	const rows = $derived.by(() => {
		const k = sortKey ?? columns[0]?.key;
		if (!k) return baseRows;
		return [...baseRows].sort((a, b) => {
			const av = a[k] ?? 0;
			const bv = b[k] ?? 0;
			if (typeof av === 'string' || typeof bv === 'string') return String(av).localeCompare(String(bv)) * sortDir;
			return (av - bv) * sortDir;
		});
	});

	// Max per column for the inline bars.
	const maxes = $derived(
		Object.fromEntries(columns.map((c) => [c.key, Math.max(0, ...baseRows.map((r) => Number(r[c.key]) || 0))]))
	);

	function sortBy(k: string) {
		if (sortKey === k) sortDir = sortDir === 1 ? -1 : 1;
		else {
			sortKey = k;
			sortDir = -1;
		}
	}

	function barWidth(c: Column, v: any) {
		const m = maxes[c.key];
		if (!m || c.fmt === 'text' || c.higherIsBetter == null) return 0;
		return Math.max(0, Math.min(100, (Number(v) / m) * 100));
	}
</script>

<!-- Bounded height: the table scrolls inside the card, so the horizontal scrollbar is always on
     screen instead of at the very bottom of a long table. Header, first column and totals stay put. -->
<div class="card max-h-[calc(100vh-8rem)] overflow-auto overscroll-contain">
	<table class="w-full border-separate border-spacing-0 text-sm">
		<thead class="sticky top-0 z-10 bg-panel">
			<tr class="text-left text-xs text-muted">
				<th class="sticky left-0 z-20 border-b border-line bg-panel px-4 py-2.5 font-medium">
					<button onclick={() => sortBy('name')} class="hover:text-text">{mode === 'party' ? 'Party' : 'Player'}</button>
				</th>
				{#if mode === 'player'}
					<th class="border-b border-line px-2 py-2.5 text-right font-medium">
						<button onclick={() => sortBy('group')} class="hover:text-text">Pty</button>
					</th>
				{/if}
				{#if extraLead}
					<th class="border-b border-line px-2 py-2.5 text-right font-medium">
						<button onclick={() => sortBy(extraLead.key)} class="hover:text-text">{extraLead.label}</button>
					</th>
				{/if}
				{#each columns as c (c.key)}
					<th class="border-b border-line px-3 py-2.5 text-right font-medium whitespace-nowrap" title={c.description}>
						<button onclick={() => sortBy(c.key)} class="hover:text-text {sortKey === c.key ? 'text-accent' : ''}">
							{c.label}{#if sortKey === c.key}<span class="ml-0.5">{sortDir === -1 ? '↓' : '↑'}</span>{/if}
						</button>
					</th>
				{/each}
			</tr>
		</thead>
		<tbody>
			{#each rows as r, i (r.name + '-' + i)}
				<tr class="group hover:bg-panel-2 {r.in_fight === false ? 'opacity-45' : ''}">
					<td class="sticky left-0 z-[5] border-b border-line/50 bg-panel px-4 py-2 whitespace-nowrap group-hover:bg-panel-2">
						{#if mode === 'party'}
							<div class="font-medium">{r.name} <span class="text-xs text-faint">· {r.members}</span></div>
							<div class="mt-0.5 flex gap-1">
								{#each r.professions ?? [] as p}
									<span class="size-2 rounded-full" style="background:{profColor(p)}" title={p}></span>
								{/each}
							</div>
						{:else}
							{@const href = rowHref?.(r)}
							<div class="flex items-center gap-2">
								<span class="h-6 w-1 rounded-full" style="background:{profColor(r.profession)}"></span>
								<div class="min-w-0">
									<div class="flex items-center gap-1.5 font-medium">
										{#if href}<a {href} class="hover:underline">{r.name}</a>{:else}{r.name}{/if}
										{#if r.is_commander}<span class="chip bg-accent/15 px-1 text-[10px] text-accent">TAG</span>{/if}
									</div>
									<div class="text-xs text-faint">{r.profession}{r.in_fight === false ? ' · not in fight' : ''}</div>
								</div>
							</div>
						{/if}
					</td>
					{#if mode === 'player'}
						<td class="tabular border-b border-line/50 px-2 py-2 text-right text-muted">{r.group}</td>
					{/if}
					{#if extraLead}
						<td class="tabular border-b border-line/50 px-2 py-2 text-right text-muted">{r[extraLead.key]}</td>
					{/if}
					{#each columns as c (c.key)}
						{@const v = r[c.key]}
						{@const w = barWidth(c, v)}
						<td class="tabular relative border-b border-line/50 px-3 py-2 text-right whitespace-nowrap">
							{#if w > 0}
								<span
									class="absolute inset-y-1.5 right-1 rounded-sm {c.higherIsBetter ? 'bg-accent/12' : 'bg-loss/12'}"
									style="width: calc({w}% - 0.5rem)"
								></span>
							{/if}
							<span class="relative {Number(v) === 0 ? 'text-faint' : ''}">{fmtValue(v, c.fmt)}</span>
						</td>
					{/each}
				</tr>
			{/each}
		</tbody>
		{#if squad && mode === 'player'}
			<tfoot class="sticky bottom-0 z-10">
				<tr class="font-medium">
					<td class="sticky left-0 bg-raised px-4 py-2">Squad total</td>
					<td class="bg-raised"></td>
					{#if extraLead}<td class="bg-raised"></td>{/if}
					{#each columns as c (c.key)}
						<td class="tabular bg-raised px-3 py-2 text-right">{fmtValue(squad[c.key], c.fmt)}</td>
					{/each}
				</tr>
			</tfoot>
		{/if}
	</table>
</div>
