#![allow(non_snake_case)] // the crate is named after the DLL (WvWAnalyzer.dll)
//! WvW Analyzer in-game overlay: a Nexus addon that shows the analyzer's fight debriefs.
//!
//! It only draws a window. Everything it shows comes from the WvW Analyzer app over
//! 127.0.0.1; the only game state it reads is MumbleLink's "in combat" flag (to hold back
//! auto-show). It sends no input, chat or game actions.

pub mod client;
pub mod model;
pub mod settings;
pub mod view;

#[cfg(windows)]
mod addon;
#[cfg(windows)]
mod ui;
