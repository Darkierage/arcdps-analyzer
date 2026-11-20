//! Addon options, stored in `addons/WvWAnalyzer/settings.json`.

use serde::{Deserialize, Serialize};
use std::path::Path;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct Settings {
    /// Open the window when a new fight has been analyzed (only out of combat).
    pub auto_show: bool,
    /// Hide the window while in combat.
    pub hide_in_combat: bool,
    /// Window background opacity, 0..1.
    pub opacity: f32,
    /// Whether the window was open when the game closed.
    pub open: bool,
}

impl Default for Settings {
    fn default() -> Self {
        Self { auto_show: true, hide_in_combat: true, opacity: 0.85, open: false }
    }
}

impl Settings {
    pub fn load(path: &Path) -> Self {
        std::fs::read_to_string(path)
            .ok()
            .and_then(|t| serde_json::from_str::<Settings>(&t).ok())
            .map(Settings::sanitized)
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

    #[test]
    fn round_trip_and_defaults() {
        let dir = std::env::temp_dir().join(format!("wvwa-settings-{}", std::process::id()));
        let path = dir.join("settings.json");
        assert_eq!(Settings::load(&path), Settings::default());
        let s = Settings { auto_show: false, opacity: 2.0, ..Settings::default() };
        s.save(&path).unwrap();
        let loaded = Settings::load(&path);
        assert!(!loaded.auto_show);
        assert_eq!(loaded.opacity, 1.0);
        std::fs::write(&path, "not json").unwrap();
        assert_eq!(Settings::load(&path), Settings::default());
        std::fs::remove_dir_all(dir).unwrap();
    }
}
