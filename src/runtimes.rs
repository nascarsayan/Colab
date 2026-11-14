//! Offline catalog derived from the same enum used by `session create`.
use crate::Runtime;
use anyhow::{Context, Result};
use clap::ValueEnum;

pub fn list(json: bool) -> Result<()> {
    let mut rows = Vec::new();
    for runtime in Runtime::value_variants() {
        let name = runtime
            .to_possible_value()
            .context("Runtime type has no CLI name")?;
        let kind = match runtime {
            Runtime::Cpu => "cpu",
            Runtime::V5e1 | Runtime::V6e1 => "tpu",
            _ => "gpu",
        };
        rows.push(serde_json::json!({"runtime":name.get_name(),"kind":kind}));
    }
    if json {
        println!("{}", serde_json::to_string_pretty(&rows)?);
    } else {
        println!("{:<12} TYPE", "RUNTIME");
        for row in rows {
            println!(
                "{:<12} {}",
                row["runtime"].as_str().unwrap_or_default(),
                row["kind"].as_str().unwrap_or_default().to_uppercase()
            );
        }
        println!("\nSupported by this CLI; account entitlement, quota, and capacity determine availability.\nCreate: Colab session create --runtime TYPE\nActive sessions: Colab session list");
    }
    Ok(())
}
