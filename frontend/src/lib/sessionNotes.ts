// The footnote under the session's stat tables: how the values in the rows were combined.

export function statTableNote(mode: 'player' | 'party', perMin: boolean, hiddenPlayers = 0): string {
	const per = perMin ? ' per minute in fights' : '';
	if (mode === 'party') {
		return (
			"One row per party number, over the fights it was in; the number next to it is its usual size (hover for " +
			"everyone who played in it). Counts and amounts are the members' totals" + per + "; generation and DPS are " +
			"the members' sums, and uptime, stacks and distances their averages, each weighted by fight length."
		);
	}
	const hidden = hiddenPlayers ? ` ${hiddenPlayers} player${hiddenPlayers === 1 ? '' : 's'} with less time hidden.` : '';
	return (
		'One row per account, over the fights they were in. Counts and amounts are totals' + per + '; uptime, ' +
		'generation, stacks and distances are averages weighted by time in each fight; DPS is damage / time in fights.' +
		hidden +
		' Click a name to see that player fight by fight.'
	);
}
