// Replay and video sync helpers (plan 18).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import type { ReplayActor } from '#lib/api.ts';
import { bounds, clockLabel, Clock, facingAt, jumpTarget, positionAt, stateAt } from '#lib/replay.ts';
import { inFile, offsetFor, offsetLabel, outsideNote, pausedBefore, videoTime } from '#lib/videoSync.ts';

const actor = (over: Partial<ReplayActor> = {}): ReplayActor => ({
	kind: 'squad',
	name: 'A',
	profession: 'Firebrand',
	start: 1000,
	end: 1900,
	// Samples every 300 ms from 1000: (0,0) (30,0) (30,40) (30,40)
	p: [0, 0, 30, 0, 30, 40, 30, 40],
	o: [0, 90, 180, 180],
	down: [[1300, 1600]],
	dead: [],
	dc: [],
	...over
});

test('positions interpolate between samples and are absent outside them', () => {
	const a = actor();
	assert.deepEqual(positionAt(a, 1000, 300), [0, 0]);
	assert.deepEqual(positionAt(a, 1150, 300), [15, 0]);
	assert.deepEqual(positionAt(a, 1450, 300), [30, 20]);
	assert.deepEqual(positionAt(a, 1900, 300), [30, 40]);
	assert.equal(positionAt(a, 999, 300), null);
	assert.equal(positionAt(a, 1901, 300), null);
	assert.equal(facingAt(a, 1310, 300), 90);
});

test('state: down, dead and disconnected intervals, absent outside the samples', () => {
	const a = actor({ dead: [[1700, 1900]], dc: [[1850, 2000]] });
	assert.equal(stateAt(a, 1100), 'up');
	assert.equal(stateAt(a, 1300), 'down');
	assert.equal(stateAt(a, 1600), 'up'); // end of an interval is exclusive
	assert.equal(stateAt(a, 1750), 'dead');
	assert.equal(stateAt(a, 1860), 'dc');
	assert.equal(stateAt(a, 500), 'absent');
});

test('bounds, jump lead-in and clock label', () => {
	assert.deepEqual(bounds([actor(), actor({ p: [-5, 2, 100, 7] })]), [-5, 0, 100, 40]);
	assert.equal(bounds([]), null);
	assert.equal(jumpTarget(10, 3), 7);
	assert.equal(jumpTarget(1, 3), 0);
	assert.equal(clockLabel(83.25), '1:23.3');
	assert.equal(clockLabel(5), '0:05.0');
});

test('the shared clock plays at a rate, pauses, seeks and stops at the end', () => {
	let now = 0;
	const c = new Clock(10, () => now);
	c.seek(2);
	c.play();
	now = 1000;
	assert.equal(c.time(), 3);
	c.setRate(2);
	now = 2000;
	assert.equal(c.time(), 5);
	c.pause();
	now = 9000;
	assert.equal(c.time(), 5);
	c.play();
	now = 12000;
	assert.equal(c.time(), 10);
	assert.equal(c.playing, false);
	c.play(); // at the end: plays from the start again
	assert.equal(c.time(), 0);
	c.seek(-3);
	assert.equal(c.time(), 0);
});

const START = Date.UTC(2026, 10, 17, 19, 0, 0); // the fight's second 0

test('fight second -> video second, with offset and pauses', () => {
	const v = { startMs: START - 120_000, endMs: null, offsetMs: 0, pauses: [] as [number, number][] };
	assert.equal(videoTime(v, START, 0), 120);
	assert.equal(videoTime(v, START, 30), 150);
	assert.equal(videoTime({ ...v, offsetMs: 1500 }, START, 0), 121.5);
	// Paused for 20 s from 10 s into the fight: later moments are 20 s earlier in the file.
	const paused = { ...v, pauses: [[START + 10_000, START + 30_000]] as [number, number][] };
	assert.equal(videoTime(paused, START, 5), 125);
	assert.equal(videoTime(paused, START, 20), 130); // inside the pause: the last frame before it
	assert.equal(videoTime(paused, START, 40), 140);
	assert.equal(pausedBefore(paused.pauses, START + 15_000), 5000);
});

test('Sync here: the offset that puts this fight second at this video second', () => {
	const v = { startMs: START - 120_000, endMs: null, offsetMs: 900, pauses: [] as [number, number][] };
	const off = offsetFor(v, START, 30, 151.25);
	assert.equal(off, 1250);
	assert.equal(videoTime({ ...v, offsetMs: off }, START, 30), 151.25);
});

test('outside the file: notes and labels', () => {
	assert.equal(inFile(-1, 100), false);
	assert.equal(inFile(50, null), true);
	assert.equal(inFile(101, 100), false);
	assert.equal(outsideNote(-30, 100), 'starts 30 s after this moment');
	assert.equal(outsideNote(100 + 600, 100), 'ends 10 min before this moment');
	assert.equal(outsideNote(10, 100), null);
	assert.equal(offsetLabel(0), '0 s');
	assert.equal(offsetLabel(1500), '+1.5 s');
	assert.equal(offsetLabel(-2000), '−2 s');
});

test('a reused video id gets another address (no cached copy of the old file)', async () => {
	const { videoUrl } = await import('#lib/api.ts');
	const a = videoUrl({ id: 1, startMs: 1000 });
	assert.equal(a, '/api/videos/1/file?v=1000');
	assert.notEqual(a, videoUrl({ id: 1, startMs: 2000 }));
});
