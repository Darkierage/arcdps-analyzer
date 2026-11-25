//! Addon options, stored in `addons/WvWAnalyzer/settings.json`.

use serde::{Deserialize, Serialize};
use std::path::Path;

/// What happens when a new fight has been analyzed (only out of combat).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AfterFight {
    /// The small panel with the result and the top problems.
    #[default]
    Panel,
    /// The full window, on the new fight.
    Window,
    Nothing,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Settings {
    pub after_fight: AfterFight,
    /// Hide the window while in combat.
    pub hide_in_combat: bool,
    /// Window background opacity, 0..1.
    pub opacity: f32,
    /// Whether the window was open when the game closed.
    pub open: bool,
}

impl Default for Settings {
    fn default() -> Self {
        Self { after_fight: AfterFight::Panel, hide_in_combat: true, opacity: 0.85, open: false }
    }
}

/// The file as stored, by this addon or an older one (0.5.0 to 0.6.x wrote `auto_show`).
/// Anything missing or unreadable falls back to its default.
#[derive(Deserialize, Default)]
#[serde(default)]
struct Stored {
    after_fight: Option<serde_json::Value>,
    auto_show: Option<bool>,
    hide_in_combat: Option<bool>,
    opacity: Option<f32>,
    open: Option<bool>,
}

impl Stored {
    fn migrate(self) -> Settings {
        let d = Settings::default();
        let after_fight = match self.after_fight.and_then(|v| serde_json::from_value(v).ok()) {
            Some(a) => a,
            // "Show the window when a new fight is analyzed": off stays off; on (the old
            // default) becomes the small panel.
            None if self.auto_show == Some(false) => AfterFight::Nothing,
            None => AfterFight::Panel,
        };
        Settings {
            after_fight,
            hide_in_combat: self.hide_in_combat.unwrap_or(d.hide_in_combat),
            opacity: self.opacity.unwrap_or(d.opacity),
            open: self.open.unwrap_or(d.open),
        }
    }
}

impl Settings {
    pub fn load(path: &Path) -> Self {
        std::fs::read_to_string(path)
            .ok()
            .and_then(|t| serde_json::from_str::<Stored>(&t).ok())
            .map(|s| s.migrate().sanitized())
            .unwrap_or_default()
    }

    pub fn save(&self, path: &Path) -> std::io::Result<()> {
        if let Some(dir) = path.parent() {
            std::fs::create_dir_all(dir)?;
        }
        let text = serde_json::to_string_pretty(self).map_err(std::io::Error::other)?;
        std::fs::write(path, text)
    }

    fn sanitized(mut self) -> Self {
        if !self.opacity.is_finite() {
            self.opacity = Settings::default().opacity;
        }
        self.opacity = self.opacity.clamp(0.0, 1.0);
        self
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp(name: &str) -> std::path::PathBuf {
        std::env::temp_dir().join(format!("wvwa-settings-{name}-{}", std::process::id()))
    }

    #[test]
    fn round_trip_and_defaults() {
        let dir = temp("round-trip");
        let path = dir.join("settings.json");
        assert_eq!(Settings::load(&path), Settings::default());
        let s = Settings { after_fight: AfterFight::Window, opacity: 2.0, ..Settings::default() };
        s.save(&path).unwrap();
        let loaded = Settings::load(&path);
        assert_eq!(loaded.after_fight, AfterFight::Window);
        assert_eq!(loaded.opacity, 1.0);
        assert!(!std::fs::read_to_string(&path).unwrap().contains("auto_show"));
        std::fs::write(&path, "not json").unwrap();
        assert_eq!(Settings::load(&path), Settings::default());
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn migrates_the_old_auto_show_setting() {
        let dir = temp("migrate");
        let path = dir.join("settings.json");
        std::fs::create_dir_all(&dir).unwrap();
        let old = |auto_show: &str| {
            format!(
                r#"{{"auto_show": {auto_show}, "hide_in_combat": false, "opacity": 0.5, "open": true}}"#
            )
        };
        std::fs::write(&path, old("false")).unwrap();
        let s = Settings::load(&path);
        assert_eq!(s.after_fight, AfterFight::Nothing);
        assert!(!s.hide_in_combat && s.opacity == 0.5 && s.open); // the rest is kept
        std::fs::write(&path, old("true")).unwrap();
        assert_eq!(Settings::load(&path).after_fight, AfterFight::Panel);
        std::fs::write(&path, r#"{"opacity": 0.7}"#).unwrap();
        assert_eq!(Settings::load(&path).after_fight, AfterFight::Panel);
        // A value this addon doesn't know (a newer one wrote it): the default, not a reset.
        std::fs::write(&path, r#"{"after_fight": "later", "opacity": 0.7}"#).unwrap();
        let s = Settings::load(&path);
        assert_eq!((s.after_fight, s.opacity), (AfterFight::Panel, 0.7));
        // Once saved, the new key wins over a leftover old one.
        std::fs::write(&path, r#"{"after_fight": "window", "auto_show": false}"#).unwrap();
        assert_eq!(Settings::load(&path).after_fight, AfterFight::Window);
        std::fs::remove_dir_all(dir).unwrap();
    }
}
