<script lang="ts">
	// Full-window drop target: drop a log, several logs or whole folders anywhere in the app.
	import { onMount } from 'svelte';
	import { collectDropped, hasFiles } from '#lib/drop.ts';
	import { importer } from '#lib/importer.svelte.ts';
	import { toasts } from '#lib/live.svelte.ts';
	import Icon from './Icon.svelte';

	let active = $state(false);
	let depth = 0; // dragenter/leave fire for every child element

	onMount(() => {
		const enter = (e: DragEvent) => {
			if (!hasFiles(e.dataTransfer)) return;
			e.preventDefault();
			depth++;
			active = true;
		};
		const over = (e: DragEvent) => {
			if (!hasFiles(e.dataTransfer)) return;
			e.preventDefault();
			if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
		};
		const leave = (e: DragEvent) => {
			if (!hasFiles(e.dataTransfer)) return;
			depth = Math.max(0, depth - 1);
			if (depth === 0) active = false;
		};
		const drop = async (e: DragEvent) => {
			if (!hasFiles(e.dataTransfer)) return;
			e.preventDefault();
			depth = 0;
			active = false;
			// Drops inside the import dialog's own zone are handled there.
			if ((e.target as HTMLElement | null)?.closest('[data-own-drop]')) return;
			try {
				const { logs, ignored } = await collectDropped(e.dataTransfer!);
				if (ignored) toasts.push(`Ignored ${ignored} file${ignored === 1 ? '' : 's'} that aren't arcdps logs`, 'info');
				await importer.start(logs);
			} catch (err) {
				toasts.error(err);
			}
		};
		window.addEventListener('dragenter', enter);
		window.addEventListener('dragover', over);
		window.addEventListener('dragleave', leave);
		window.addEventListener('drop', drop);
		return () => {
			window.removeEventListener('dragenter', enter);
			window.removeEventListener('dragover', over);
			window.removeEventListener('dragleave', leave);
			window.removeEventListener('drop', drop);
		};
	});
</script>

{#if active}
	<div class="pointer-events-none fixed inset-0 z-50 grid place-items-center bg-bg/80 p-8 backdrop-blur-sm">
		<div class="flex h-full w-full flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed border-accent bg-accent/5">
			<div class="grid size-14 place-items-center rounded-full bg-accent/15">
				<Icon name="upload" class="size-7 text-accent" />
			</div>
			<div class="text-lg font-semibold">Drop to import</div>
			<div class="text-sm text-muted">A log, several logs or a whole folder · non-WvW logs are skipped</div>
		</div>
	</div>
{/if}
