//! Decisions that aren't drawing, kept as plain functions so they are unit tested.

use crate::model::Note;

fn serious(severity: &str) -> bool {
    matches!(severity, "critical" | "major")
}

/// Whether issue card `i` starts open: critical and major cards do. A fight with nothing
/// serious opens its first card, so the top advice is always readable.
pub fn starts_open(issues: &[Note], i: usize) -> bool {
    match issues.get(i) {
        Some(n) if serious(&n.severity) => true,
        Some(_) => i == 0 && !issues.iter().any(|n| serious(&n.severity)),
        None => false,
    }
}

/// The fact's first letter in upper case: templates write "we lost 63 boons..." to fit
/// mid-sentence in the app; a card starts a sentence.
pub fn capitalize_first(s: &str) -> String {
    let mut chars = s.chars();
    match chars.next() {
        Some(c) => c.to_uppercase().chain(chars).collect(),
        None => String::new(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn note(severity: &str) -> Note {
        Note { severity: severity.into(), ..Note::default() }
    }

    #[test]
    fn serious_cards_start_open() {
        let issues = [note("critical"), note("major"), note("minor"), note("info")];
        let open: Vec<bool> = (0..4).map(|i| starts_open(&issues, i)).collect();
        assert_eq!(open, [true, true, false, false]);
        assert!(!starts_open(&issues, 9));
    }

    #[test]
    fn nothing_serious_opens_the_first_card() {
        let issues = [note("minor"), note("minor"), note("info")];
        let open: Vec<bool> = (0..3).map(|i| starts_open(&issues, i)).collect();
        assert_eq!(open, [true, false, false]);
        assert!(!starts_open(&[], 0));
    }

    #[test]
    fn capitalizes_only_the_first_letter() {
        assert_eq!(
            capitalize_first("we lost 63 boons; real strippers: 2."),
            "We lost 63 boons; real strippers: 2."
        );
        assert_eq!(capitalize_first("Party 6 lacked cleanses"), "Party 6 lacked cleanses");
        assert_eq!(capitalize_first("łódź"), "Łódź");
        assert_eq!(capitalize_first("4 downed"), "4 downed");
        assert_eq!(capitalize_first(""), "");
    }
}
