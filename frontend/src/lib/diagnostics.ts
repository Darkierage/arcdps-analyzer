// Troubleshooting: page errors go to the app log (the window has no console a user could open),
// and the diagnostics report is copied for the user to send. Nothing leaves this PC by itself.
import { api } from './api.ts';
import { live, toasts } from './live.svelte.ts';

const MAX_REPORTS = 20; // per page load; the backend caps the whole run too
const seen = new Set<string>();
let installed = false;

function report(message: string, stack?: string) {
	// Chromium's harmless layout warning, and opaque errors from other origins.
	if (!message || message.includes('ResizeObserver loop') || message === 'Script error.') return;
	const key = `${message}\n${(stack ?? '').slice(0, 300)}`;
	if (seen.has(key) || seen.size >= MAX_REPORTS) return;
	seen.add(key);
	fetch('/api/client-error', {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({
			message: message.slice(0, 2000),
			stack: stack?.slice(0, 8000),
			url: location.pathname + location.search
		})
	}).catch(() => {
		/* backend gone: nothing to do */
	});
}

export function installErrorReporting() {
	if (installed || typeof window === 'undefined') return;
	installed = true;
	window.addEventListener('error', (e) => report(e.message || String(e.error ?? ''), e.error?.stack));
	window.addEventListener('unhandledrejection', (e) => {
		const r = e.reason;
		report(r instanceof Error ? r.message : String(r), r instanceof Error ? r.stack : undefined);
	});
}

function legacyCopy(text: string): boolean {
	const ta = document.createElement('textarea');
	ta.value = text;
	ta.style.position = 'fixed';
	ta.style.opacity = '0';
	document.body.appendChild(ta);
	ta.select();
	try {
		return document.execCommand('copy');
	} catch {
		return false;
	} finally {
		ta.remove();
	}
}

/** Build the report, copy it, and say where the saved copy is. */
export async function copyDiagnostics(): Promise<void> {
	try {
		const { text, path } = await api.diagnostics();
		let copied = false;
		try {
			await navigator.clipboard.writeText(text);
			copied = true;
		} catch {
			copied = legacyCopy(text);
		}
		if (copied) {
			toasts.push(
				'Diagnostics copied. Paste them into a message to whoever helps you' +
					(path ? ' (also saved as diagnostics.txt in the app folder).' : '.'),
				'success',
				9000
			);
		} else if (path) {
			toasts.push(`Couldn't copy. The report is saved as ${path}; send that file.`, 'info', 12000);
			api.openDataFolder().catch(() => {});
		} else {
			throw new Error("Couldn't copy or save the diagnostics report");
		}
	} catch (e) {
		toasts.error(e);
	}
}

export async function openDataFolder(): Promise<void> {
	try {
		const r = await api.openDataFolder();
		if (!r.opened) toasts.push(`App folder: ${r.path}`, 'info', 12000);
	} catch (e) {
		toasts.error(e);
	}
}

export async function dismissCrashes(): Promise<void> {
	try {
		await api.dismissCrashes();
		live.crashes = [];
	} catch (e) {
		toasts.error(e);
	}
}
