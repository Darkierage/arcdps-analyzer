<script lang="ts">
	// Header switch for the mode new fights get: flip it on before a GvG block, off after.
	import { api } from '#lib/api.ts';
	import { live, toasts } from '#lib/live.svelte.ts';

	let busy = $state(false);
	const gvg = $derived(live.fightMode === 'gvg');

	async function toggle() {
		busy = true;
		const mode = gvg ? 'zerg' : 'gvg';
		try {
			await api.saveSettings({ fight_mode: mode });
			live.fightMode = mode;
			toasts.push(mode === 'gvg' ? 'New fights are analyzed as GvG' : 'New fights are analyzed as zerg fights', 'info');
		} catch (e) {
			toasts.error(e);
		} finally {
			busy = false;
		}
	}
</script>

<button
	class="flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition disabled:opacity-60 {gvg
		? 'border-accent/60 bg-accent/15 text-text'
		: 'border-line text-muted hover:bg-panel-2 hover:text-text'}"
	onclick={toggle}
	disabled={busy}
	aria-pressed={gvg}
	title="GvG mode: rounds end with a call-off, so downs left at the call-off and kills after it are not counted. Applies to fights added from now on; existing fights can be switched on their own page."
>
	<span class="relative inline-flex h-3.5 w-6 shrink-0 rounded-full transition {gvg ? 'bg-accent' : 'bg-raised'}">
		<span class="absolute top-0.5 size-2.5 rounded-full bg-white transition-all {gvg ? 'left-3' : 'left-0.5'}"></span>
	</span>
	GvG
</button>
