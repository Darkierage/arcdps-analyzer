// Collect arcdps log files from a drag & drop, including whole folders (recursively).

export const LOG_RE = /\.(zevtc|evtc)(\.zip)?$/i;

type Entry = FileSystemEntry;

function readAllEntries(dir: FileSystemDirectoryEntry): Promise<Entry[]> {
	const reader = dir.createReader();
	const all: Entry[] = [];
	// readEntries returns batches (~100 in Chromium) until an empty batch.
	return new Promise((resolve, reject) => {
		const next = () =>
			reader.readEntries((batch) => {
				if (!batch.length) resolve(all);
				else {
					all.push(...batch);
					next();
				}
			}, reject);
		next();
	});
}

function entryFile(entry: FileSystemFileEntry): Promise<File> {
	return new Promise((resolve, reject) => entry.file(resolve, reject));
}

async function walk(entry: Entry, out: File[]): Promise<void> {
	if (entry.isFile) {
		if (LOG_RE.test(entry.name)) out.push(await entryFile(entry as FileSystemFileEntry));
	} else if (entry.isDirectory) {
		for (const child of await readAllEntries(entry as FileSystemDirectoryEntry)) await walk(child, out);
	}
}

/** True when a drag carries files/folders (not text or links). */
export function hasFiles(dt: DataTransfer | null | undefined): boolean {
	return !!dt && Array.from(dt.types).includes('Files');
}

/** All log files in a drop; folders are walked recursively. Returns logs and the count of ignored files. */
export async function collectDropped(dt: DataTransfer): Promise<{ logs: File[]; ignored: number }> {
	const entries = Array.from(dt.items ?? [])
		.filter((i) => i.kind === 'file')
		.map((i) => i.webkitGetAsEntry?.())
		.filter((e): e is Entry => !!e);
	const logs: File[] = [];
	if (entries.length) {
		for (const e of entries) await walk(e, logs);
	} else {
		logs.push(...Array.from(dt.files).filter((f) => LOG_RE.test(f.name)));
	}
	// Only count non-log files dropped directly; other files inside folders are expected.
	const ignored = entries.filter((e) => e.isFile && !LOG_RE.test(e.name)).length;
	return { logs: dedupe(logs), ignored };
}

/** Logs from an <input type=file> (files or a picked folder). */
export function collectInput(list: FileList | null | undefined): { logs: File[]; ignored: number } {
	const all = Array.from(list ?? []);
	const logs = all.filter((f) => LOG_RE.test(f.name));
	const isFolder = all.some((f) => f.webkitRelativePath);
	return { logs: dedupe(logs), ignored: isFolder ? 0 : all.length - logs.length };
}

function dedupe(files: File[]): File[] {
	const seen = new Map<string, File>();
	for (const f of files) if (!seen.has(f.name)) seen.set(f.name, f);
	return [...seen.values()];
}

/** Date of a log from its arcdps file name (YYYYMMDD-HHMMSS), falling back to lastModified. */
export function logDate(f: File): Date {
	const m = f.name.match(/^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})/);
	if (m) return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]);
	return new Date(f.lastModified);
}
