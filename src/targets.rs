use anyhow::{Context, Result};
use serde_json::Value;
use std::{fs, path::PathBuf};

pub fn list(session: &str, all_sessions: bool, json: bool) -> Result<()> {
    let home = PathBuf::from(std::env::var_os("HOME").context("HOME is unset")?);
    let dir = home.join(".config/Colab/sync");
    let mut records = Vec::new();
    let mut legacy = 0;
    if dir.exists() {
        for entry in fs::read_dir(&dir)? {
            let path = entry?.path();
            let name = path
                .file_name()
                .and_then(|n| n.to_str())
                .unwrap_or_default();
            if name.ends_with(".target.json") {
                let record: Value = serde_json::from_slice(&fs::read(&path)?)
                    .with_context(|| format!("Invalid sync target metadata: {}", path.display()))?;
                if all_sessions || record["session"].as_str() == Some(session) {
                    records.push(record);
                }
            } else if name.ends_with(".json")
                && !path
                    .with_file_name(format!("{}.target.json", name.trim_end_matches(".json")))
                    .exists()
            {
                legacy += 1;
            }
        }
    }
    records.sort_by(|a, b| {
        a["session"]
            .as_str()
            .cmp(&b["session"].as_str())
            .then_with(|| a["left"].as_str().cmp(&b["left"].as_str()))
            .then_with(|| a["right"].as_str().cmp(&b["right"].as_str()))
    });
    if json {
        println!("{}", serde_json::to_string_pretty(&records)?);
    } else if records.is_empty() {
        println!(
            "No recorded sync targets{}.",
            if all_sessions {
                String::new()
            } else {
                format!(" for session {session}")
            }
        );
    } else {
        for r in records {
            println!(
                "[{}] {} {} {}\n  Last successful sync (UTC): {}",
                r["session"].as_str().unwrap_or("?"),
                r["left"].as_str().unwrap_or("?"),
                r["direction"].as_str().unwrap_or("?"),
                r["right"].as_str().unwrap_or("?"),
                r["last_success_utc"].as_str().unwrap_or("unknown")
            );
        }
    }
    if legacy > 0 {
        eprintln!("Found {legacy} older sync baseline(s) without target names. Rerun their sync commands once to register the pairs; old paths cannot be recovered from baseline hashes.");
    }
    Ok(())
}
