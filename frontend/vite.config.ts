import tailwindcss from '@tailwindcss/vite';
import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

// Backend (FastAPI) port used during development; the built app is served by FastAPI itself.
const BACKEND = 'http://127.0.0.1:8765';

export default defineConfig({
	plugins: [
		tailwindcss(),
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},
			// Static single-page app: built into frontend/build and served by the Python backend.
			adapter: adapter({ fallback: 'index.html' })
		})
	],
	server: {
		proxy: {
			'/api': { target: BACKEND, changeOrigin: true },
			'/ws': { target: BACKEND.replace('http', 'ws'), ws: true }
		}
	}
});
