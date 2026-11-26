// Unit tests for frontend helpers (run with `npm test`; Node runs the TypeScript directly).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { compact as compactish, escapeHtml, profColor } from '#lib/format.ts';
import { compare, fightLink, fmtNumber, momentWindow, myPlaySearch, parseScope, scopeQuery } from '#lib/myplay.ts';
import { trendTooltipHtml } from '#lib/trendTooltip.ts';
import { rememberSession, sessionBackHref } from '#lib/sessionNav.ts';
import { findSeriesRow, seriesKey } from '#lib/players.ts';
import { bannerKind, downloadProgress, unfinishedKey } from '#lib/update.ts';
import type { UpdateStatus } from '#lib/api.ts';

const EVIL = '<img src=x onerror=alert(1)>';

test('the trend tooltip escapes names and map from the log', () => {
	const html = trendTooltipHtml(
		{ start: '2026-11-21 20:00:00 +01:00', map: `${EVIL} Borderlands`, result: 'win' },
		[{ marker: '<span class="dot"></span>', name: `${EVIL}: Stability uptime`, value: 42 }],
		'pct'
	);
	assert.ok(!html.includes('<img'), html);
	assert.ok(html.includes('&#60;img src=x onerror=alert(1)&#62;'));
	assert.ok(html.includes('<span class="dot"></span>'), 'the chart marker stays HTML');
	assert.ok(html.includes('42%'));
	assert.equal(escapeHtml(`a"b'c&`), 'a&#34;b&#39;c&#38;');
});

test('a player listed with several professions gets the first one\'s color', () => {
	assert.equal(profColor('Firebrand, Willbender'), profColor('Firebrand'));
	assert.notEqual(profColor('Firebrand'), profColor('Nobody'));
});

test('the fight page links back to the session as it was left', () => {
	assert.equal(sessionBackHref(4), '/sessions/4');
	rememberSession(4, '/sessions/4?tab=boons&player=Ann.1234');
	assert.equal(sessionBackHref(4), '/sessions/4?tab=boons&player=Ann.1234');
	assert.equal(sessionBackHref(5), '/sessions/5'); // another session: its default view
	rememberSession(4, '/elsewhere'); // only the session's own URL is kept
	assert.equal(sessionBackHref(4), '/sessions/4?tab=boons&player=Ann.1234');
});

test('a ?player= picks the row it names, or the account\'s main row', () => {
	const rows = [
		{ account: 'Ann.1', series_key: 'Ann.1', in_fight: false, active_s: 300 },
		{ account: 'Ann.1', series_key: 'Ann.1#2', in_fight: true, active_s: 60 },
		{ account: 'Bob.2', in_fight: true, active_s: 10 } // analyzed before series keys
	];
	assert.equal(seriesKey(findSeriesRow(rows, 'Ann.1#2')!), 'Ann.1#2');
	assert.equal(seriesKey(findSeriesRow(rows, 'Ann.1')!), 'Ann.1');
	assert.equal(seriesKey(findSeriesRow(rows, 'Bob.2')!), 'Bob.2');
	assert.equal(findSeriesRow(rows, 'Cid.3'), null);
	// An account that is no row's key (a link from the session trend) picks its in-fight row,
	// even when a not-in-fight row has more time.
	const split = [
		{ account: 'Ann.1', series_key: 'Ann.1#a', in_fight: false, active_s: 300 },
		{ account: 'Ann.1', series_key: 'Ann.1#b', in_fight: true, active_s: 60 }
	];
	assert.equal(seriesKey(findSeriesRow(split, 'Ann.1')!), 'Ann.1#b');
});

test('a missing trend value in a fight the player was in has its own text', async () => {
	const { trendTooltipHtml } = await import('#lib/trendTooltip.ts');
	const f = { start: null, map: 'EBG', result: 'win' as const };
	const line = { marker: '', name: 'Cmd: Dist. to tag', value: null };
	assert.ok(trendTooltipHtml(f, [line], 'dist').includes('not in this fight'));
	const html = trendTooltipHtml(f, [{ ...line, missing: 'no distance (the commander, or no tag)' }], 'dist');
	assert.ok(html.includes('no distance (the commander, or no tag)') && !html.includes('not in this fight'));
});

test('the stat-table footnote describes party rows in Parties mode', async () => {
	const { statTableNote } = await import('#lib/sessionNotes.ts');
	const party = statTableNote('party', false);
	assert.ok(party.startsWith('One row per party number'));
	assert.ok(!party.includes('One row per account') && !party.includes('Click a name') && !party.includes('damage / time'));
	const players = statTableNote('player', true, 2);
	assert.ok(players.includes('One row per account') && players.includes('per minute') && players.includes('2 players with less time hidden'));
});

test('the session keeps its tab, player and trend stat in the address', async () => {
	const { parseSessionView, sessionSearch, rememberSession, sessionBackHref } = await import('#lib/sessionNav.ts');
	const tabs = ['summary', 'boons'];
	const stats = ['up_1122', 'strips'];
	const q = sessionSearch(new URLSearchParams('x=1'), { tab: 'summary', player: 'Ann.1', stat: 'strips' });
	assert.equal(q.toString(), 'x=1&player=Ann.1&stat=strips');
	assert.deepEqual(parseSessionView(q, tabs, stats), { tab: 'summary', player: 'Ann.1', stat: 'strips' });
	// Defaults stay out of the address; unknown values fall back.
	assert.equal(sessionSearch(new URLSearchParams(), { tab: 'summary', player: null, stat: 'up_1122' }).toString(), '');
	assert.deepEqual(parseSessionView(new URLSearchParams('tab=nope&stat=nope'), tabs, stats), { tab: 'summary', player: null, stat: 'up_1122' });
	// The fight page's back link returns with the stat too.
	rememberSession(7, `/sessions/7?${q}`);
	assert.equal(sessionBackHref(7), '/sessions/7?x=1&player=Ann.1&stat=strips');
});

test('the Trends tooltip escapes the session name and the problem title', async () => {
	const { sessionTooltipHtml, parseTrendStat, resultsText, TREND_STATS } = await import('#lib/trends.ts');
	const s = {
		id: 1,
		name: `${EVIL} raid`,
		kind: 'recording' as const,
		start: '2026-11-21 20:00:00 +01:00',
		fights: 7,
		results: { win: 4, even: 1, loss: 2, skirmish: 1 },
		winRate: 57.1,
		kdr: 1.25,
		deathsPerFight: 3.4,
		squadDeaths: 24,
		enemyDeaths: 30,
		topIssue: { key: 'k', title: `${EVIL} deaths`, count: 3, losses: 2, severity: 'major' as const }
	};
	const html = sessionTooltipHtml(s, parseTrendStat('winRate'));
	assert.ok(!html.includes('<img'), html);
	assert.ok(html.includes('&#60;img src=x onerror=alert(1)&#62; raid'));
	assert.ok(html.includes('Win rate: <b>57%</b>'), html);
	assert.ok(html.includes('7 fights · 4W 1E 2L +1 skirmish'), html);
	assert.ok(html.includes('(3 of 7)'));
	// A session of skirmishes only has no win rate: say so instead of "0%".
	const none = sessionTooltipHtml({ ...s, winRate: null, topIssue: null }, parseTrendStat('winRate'));
	assert.ok(none.includes('Win rate: <b>skirmishes only</b>'), none);
	assert.ok(!none.includes('Top problem'));
	assert.ok(sessionTooltipHtml(s, parseTrendStat('kdr')).includes('K/D: <b>1.25</b>'));
	assert.ok(sessionTooltipHtml({ ...s, kdr: 3 }, parseTrendStat('kdr')).includes('K/D: <b>3.00</b>'));
	// ?stat= falls back to the first stat for anything it doesn't know.
	assert.equal(parseTrendStat('nope').key, TREND_STATS[0].key);
	assert.equal(parseTrendStat(null).key, 'winRate');
	assert.equal(parseTrendStat('deathsPerFight').key, 'deathsPerFight');
	assert.equal(resultsText({ results: { win: 1, even: 0, loss: 0, skirmish: 0 } }), '1W 0E 0L');
});


test('My play scopes become API queries and stay in the URL', () => {
	assert.deepEqual(scopeQuery('last', null), { sessions: 1 });
	assert.deepEqual(scopeQuery('last5', 'Reaper'), { sessions: 5, profession: 'Reaper' });
	assert.deepEqual(scopeQuery('all', null), {});
	assert.deepEqual(scopeQuery('days30', null, new Date(2026, 10, 25, 12)), { from: '2026-10-26' });
	assert.equal(parseScope('nope'), 'last5');
	assert.equal(myPlaySearch('A.1234', 'last5', null), '?player=A.1234');
	assert.equal(myPlaySearch('A.1234', 'all', 'Firebrand'), '?player=A.1234&scope=all&spec=Firebrand');
});

test('a down links to its fight on the player at that moment', () => {
	assert.equal(fightLink(7, 'A.1234#2', 61.6), '/fights/7?player=A.1234%232&t=62');
	assert.equal(fightLink(7, null), '/fights/7');
	assert.deepEqual(momentWindow('62'), [57, 64]);
	assert.deepEqual(momentWindow('3'), [0, 5]);
	assert.equal(momentWindow(null), null);
	assert.equal(momentWindow('x'), null);
});

test('personal numbers are formatted by unit and judged by direction', () => {
	assert.equal(fmtNumber(52.4, { unit: '%', key: 'cast' }), '52%');
	assert.equal(fmtNumber(184_000, { unit: '/min', key: 'damage' }), `${compactish(184_000)} /min`);
	assert.equal(fmtNumber(null, { unit: '/min', key: 'damage' }), '–');
	assert.equal(compare(10, 8, true), 'better');
	assert.equal(compare(10, 8, false), 'worse');
	assert.equal(compare(10, 9.5, true), null);
	assert.equal(compare(10, 8, null), null);
});

test('the update banner shows a newer release until it is skipped or hidden', () => {
	const latest = { version: '0.8.0', notes: '', url: '', publishedAt: null, verified: true, verifyError: null, size: 1 };
	const u: UpdateStatus = {
		current: '0.7.0', enabled: true, checking: false, lastCheck: 1, error: null, latest, available: true,
		skipped: false, canInstall: true, blockedReason: null, download: null, unfinished: null, releasesUrl: ''
	};
	assert.equal(bannerKind(null, null), 'none');
	assert.equal(bannerKind(u, null), 'available');
	assert.equal(bannerKind({ ...u, available: false }, null), 'none');
	assert.equal(bannerKind({ ...u, skipped: true }, null), 'none');
	assert.equal(bannerKind(u, '0.8.0'), 'none'); // "Later" for this version
	assert.equal(bannerKind(u, '0.7.5'), 'available'); // a newer one than the hidden one
	const downloading = { ...u, skipped: true, download: { state: 'downloading' as const, done: 1, total: 2, error: null } };
	assert.equal(bannerKind(downloading, '0.8.0'), 'available'); // a running install stays visible
	// A failed download is hidden by Later and Skip like any offer (review U1).
	const failed = { ...u, download: { state: 'failed' as const, done: 1, total: 2, error: 'x' } };
	assert.equal(bannerKind(failed, null), 'available');
	assert.equal(bannerKind(failed, '0.8.0'), 'none');
	assert.equal(bannerKind({ ...failed, skipped: true }, null), 'none');
	// An unfinished update: its banner, which Later hides; a newer release replaces it (review U6).
	const unfinished = { ...u, unfinished: { version: '0.8.0', canRetry: true } };
	assert.equal(bannerKind(unfinished, '0.8.0'), 'unfinished');
	assert.equal(bannerKind(unfinished, unfinishedKey('0.8.0')), 'none');
	const newer = { ...unfinished, latest: { ...latest, version: '0.8.1' } };
	assert.equal(bannerKind(newer, null), 'available');
	assert.equal(bannerKind({ ...newer, skipped: true }, null), 'unfinished');
	// Checks turned off: no offer from the saved check (review U3); an unfinished update still shows.
	assert.equal(bannerKind({ ...u, enabled: false }, null), 'none');
	assert.equal(bannerKind({ ...newer, enabled: false }, null), 'unfinished');
	assert.equal(downloadProgress({ done: 5 * 1024 * 1024, total: 56 * 1024 * 1024 }), '5.0 / 56 MB');
	assert.equal(downloadProgress({ done: 12 * 1024 * 1024, total: 0 }), '12 MB');
});
