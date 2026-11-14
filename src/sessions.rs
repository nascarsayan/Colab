use anyhow::{bail, Context, Result};
use std::{collections::HashSet, fs, path::PathBuf};
const WORDS: &[&str] = &[
    "Breezy", "Cloudy", "Cozy", "Dewy", "Dreamy", "Dusty", "Earthy", "Feisty", "Fluffy", "Frosty",
    "Giddy", "Glassy", "Glossy", "Happy", "Hazy", "Honey", "Icy", "Jazzy", "Leafy", "Lucky",
    "Merry", "Mighty", "Misty", "Mossy", "Peachy", "Rainy", "Rocky", "Rosy", "Rusty", "Sandy",
    "Shiny", "Silky", "Sleepy", "Snowy", "Spicy", "Starry", "Stormy", "Sunny", "Swiftly",
    "Thirsty", "Tiny", "Toasty", "Tricky", "Velvety", "Windy", "Wispy", "Witty", "Zesty",
];
const NOUNS: &[&str] = &[
    "Badger", "Birch", "Blossom", "Brook", "Cedar", "Cloud", "Comet", "Coral", "Crane", "Dawn",
    "Dolphin", "Falcon", "Fern", "Finch", "Flame", "Forest", "Fox", "Glade", "Grove", "Harbor",
    "Heron", "Island", "Jade", "Lake", "Lark", "Maple", "Marble", "Meadow", "Moon", "Moss",
    "Otter", "Owl", "Pebble", "Pine", "Plum", "Pond", "Quartz", "Raven", "Reef", "River", "Shine",
    "Sparrow", "Stone", "Sunrise", "Tiger", "Valley", "Willow", "Wren",
];
pub fn generated() -> Result<String> {
    let home = PathBuf::from(std::env::var_os("HOME").context("HOME is unset")?);
    let mut used = HashSet::new();
    for path in [
        home.join(".config/colab-cli/sessions.json"),
        home.join(".config/Colab/runtimes.json"),
    ] {
        if path.exists() {
            let state: serde_json::Value = serde_json::from_slice(&fs::read(path)?)?;
            if let Some(map) = state.as_object() {
                used.extend(map.keys().cloned());
            }
        }
    }
    for _ in 0..256 {
        let id = uuid::Uuid::new_v4();
        let bytes = id.as_bytes();
        let a = u16::from_le_bytes([bytes[0], bytes[1]]) as usize % WORDS.len();
        let b = u16::from_le_bytes([bytes[2], bytes[3]]) as usize % NOUNS.len();
        let name = format!("{}{}", WORDS[a], NOUNS[b]);
        if !used.contains(&name) {
            return Ok(name);
        }
    }
    bail!("Could not generate an unused session name; supply a name explicitly")
}
pub fn local_first() -> Result<Option<String>> {
    let home = PathBuf::from(std::env::var_os("HOME").context("HOME is unset")?);
    let path = home.join(".config/colab-cli/sessions.json");
    if !path.exists() {
        return Ok(None);
    }
    let value: serde_json::Value = serde_json::from_slice(&fs::read(path)?)?;
    Ok(value.as_object().and_then(|m| m.keys().next()).cloned())
}
pub fn select(explicit: Option<&str>, allow_new: bool) -> Result<String> {
    if let Some(name) = explicit {
        return Ok(name.into());
    }
    let candidate = generated()?;
    let mut p = crate::script_command(include_str!("select_session.py"))?;
    let output = p
        .args([candidate.as_str(), if allow_new { "1" } else { "0" }])
        .output()?;
    if !output.status.success() {
        let msg = String::from_utf8_lossy(&output.stderr);
        bail!("{}", msg.trim().trim_start_matches("Error: "))
    }
    let name = String::from_utf8(output.stdout)?.trim().to_owned();
    if name.is_empty() {
        bail!("No active session selected; run Colab session create")
    }
    eprintln!("Using session {name}");
    Ok(name)
}
