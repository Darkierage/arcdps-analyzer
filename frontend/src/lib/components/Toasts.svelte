<script lang="ts">
	import { toasts } from '#lib/live.svelte.ts';
	import Icon from './Icon.svelte';

	const style = {
		info: 'border-line-2 text-text',
		success: 'border-win/50 text-text',
		error: 'border-loss/60 text-text'
	};
	const icon = { info: 'info', success: 'check', error: 'alert' };
	const iconColor = { info: 'text-accent', success: 'text-win', error: 'text-loss' };
</script>

<div class="pointer-events-none fixed right-5 bottom-5 z-50 flex w-96 flex-col gap-2">
	{#each toasts.items as t (t.id)}
		<div
			class="pointer-events-auto flex items-start gap-2.5 rounded-xl border bg-raised px-4 py-3 text-sm shadow-xl {style[t.kind]}"
		>
			<Icon name={icon[t.kind]} class="mt-0.5 size-4 shrink-0 {iconColor[t.kind]}" />
			<span class="flex-1">{t.text}</span>
			<button class="text-faint hover:text-text" onclick={() => toasts.dismiss(t.id)} aria-label="Dismiss">
				<Icon name="x" class="size-3.5" />
			</button>
		</div>
	{/each}
</div>
