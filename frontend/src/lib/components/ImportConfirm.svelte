<script lang="ts">
	// Explicit confirmation for big imports (more than CONFIRM_THRESHOLD new logs).
	import { CONFIRM_THRESHOLD, importer, SECONDS_PER_LOG } from '#lib/importer.svelte.ts';
	import Icon from './Icon.svelte';

	const plan = $derived(importer.plan);
	const fmt = (d: Date | null) => (d ? d.toLocaleDateString([], { day: 'numeric', month: 'short', year: 'numeric' }) : '?');
	const duration = $derived.by(() => {
		const m = plan?.minutes ?? 0;
		return m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`;
	});
</script>

{#if importer.phase === 'confirm' && plan}
	<div class="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4 backdrop-blur-sm" role="presentation">
		<div class="card w-full max-w-md p-5 shadow-2xl" role="alertdialog" aria-labelledby="ic-title">
			<div class="mb-3 flex items-center gap-3">
				<div class="grid size-9 place-items-center rounded-full bg-major/15">
					<Icon name="alert" class="size-5 text-major" />
				</div>
				<h2 id="ic-title" class="text-base font-semibold">Import {plan.files.length} logs?</h2>
			</div>
			<p class="text-sm text-muted">
				This is more than {CONFIRM_THRESHOLD} logs, so it will take a while. Logs are processed one at a time
				in the background, so the app stays usable and recording still works.
			</p>
			<dl class="tabular my-4 grid grid-cols-2 gap-x-4 gap-y-2 rounded-lg bg-panel-2 p-3 text-sm">
				<dt class="text-muted">New logs</dt>
				<dd class="text-right font-medium">{plan.files.length}</dd>
				{#if plan.known}
					<dt class="text-muted">Already imported</dt>
					<dd class="text-right text-faint">{plan.known} (skipped)</dd>
				{/if}
				<dt class="text-muted">Dates</dt>
				<dd class="text-right">{fmt(plan.from)} – {fmt(plan.to)}</dd>
				<dt class="text-muted">Days → sessions</dt>
				<dd class="text-right">{plan.days}</dd>
				<dt class="text-muted">Estimated time</dt>
				<dd class="text-right font-medium text-major">up to ~{duration}</dd>
			</dl>
			<p class="mb-5 text-xs text-faint">
				Estimate assumes ~{SECONDS_PER_LOG} s per log. Non-WvW logs (PvE, golem) are skipped instantly, which makes it
				faster. Queued logs can be cancelled from the header.
			</p>
			<div class="flex justify-end gap-2">
				<button class="btn" onclick={() => importer.cancel()}>Cancel</button>
				<button class="btn btn-primary" onclick={() => importer.confirm()}>
					<Icon name="upload" class="size-4" /> Import {plan.files.length} logs
				</button>
			</div>
		</div>
	</div>
{/if}
