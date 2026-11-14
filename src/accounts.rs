//! Explicit account selection is process-local and never retargets live SSH masters.
use anyhow::{bail, Context, Result};
use serde_json::Value;
use std::{env, fs, path::PathBuf};

pub fn root() -> Result<PathBuf> {
    Ok(PathBuf::from(env::var_os("HOME").context("HOME is unset")?).join(".config/Colab"))
}
fn registry() -> Result<Value> {
    let path = root()?.join("accounts.json");
    if !path.exists() {
        return Ok(serde_json::json!({"accounts": {}}));
    }
    Ok(serde_json::from_slice(&fs::read(path)?)?)
}
pub fn profile() -> Result<PathBuf> {
    Ok(env::var_os("COLAB_PROFILE_DIR")
        .map(PathBuf::from)
        .unwrap_or(root()?))
}
pub fn sessions_path() -> Result<PathBuf> {
    if env::var_os("COLAB_PROFILE_DIR").is_some() {
        Ok(profile()?.join("sessions.json"))
    } else {
        Ok(PathBuf::from(env::var_os("HOME").context("HOME is unset")?)
            .join(".config/colab-cli/sessions.json"))
    }
}
fn activate(email: &str, data: &Value) -> Result<()> {
    let email = email.to_lowercase();
    let item = &data["accounts"][&email];
    let id = item["id"].as_str().with_context(|| {
        format!("Account {email} is not saved. Run Colab auth login --account {email}")
    })?;
    // IDs are locally stored metadata: never allow path traversal.
    uuid::Uuid::parse_str(id).context("Invalid account profile ID")?;
    env::set_var("COLAB_ACCOUNT", &email);
    env::set_var("COLAB_PROFILE_DIR", root()?.join("accounts").join(id));
    eprintln!("Account: {email}");
    Ok(())
}
pub fn configure_login(email: Option<&str>) -> Result<()> {
    // Explicit email picks an existing account or starts a new, isolated login.
    if let Some(email) = email {
        env::set_var("COLAB_LOGIN_EMAIL", email.to_lowercase());
    }
    Ok(())
}
fn discover_legacy() -> Result<()> {
    // Discovery never opens consent or consumes program stdin.
    let output = crate::script_command(include_str!("login.py"))?
        .arg("--no-browser")
        .output()?;
    use std::io::Write;
    std::io::stderr().write_all(&output.stdout)?;
    std::io::stderr().write_all(&output.stderr)?;
    if !output.status.success() {
        bail!("No saved Google account. Run Colab auth login first.");
    }
    Ok(())
}
pub fn select(email: &str) -> Result<()> {
    let mut data = registry()?;
    if data["accounts"].as_object().is_none_or(|m| m.is_empty()) {
        discover_legacy()?;
        data = registry()?;
    }
    activate(email, &data)
}
pub fn list(filter: Option<&str>) -> Result<()> {
    let data = registry()?;
    println!("ACCOUNT");
    if let Some(accounts) = data["accounts"].as_object() {
        for email in accounts.keys() {
            if filter.is_some_and(|f| !f.eq_ignore_ascii_case(email)) {
                continue;
            }
            println!("{email}");
        }
        if accounts.is_empty() {
            println!("No saved accounts. Run Colab auth login.");
        }
    }
    Ok(())
}
pub fn sessions(filter: Option<&str>, action: &str, session: Option<&str>) -> Result<()> {
    let mut data = registry()?;
    if data["accounts"].as_object().is_none_or(|m| m.is_empty()) {
        discover_legacy()?;
        data = registry()?;
    }
    let emails: Vec<String> = if let Some(email) = filter {
        vec![email.to_lowercase()]
    } else {
        data["accounts"]
            .as_object()
            .context("Invalid accounts registry")?
            .keys()
            .cloned()
            .collect()
    };
    let mut failed = false;
    for email in emails {
        activate(&email, &data)?;
        println!("Account: {email}");
        let mut process = if let ("sessions", Some(session)) = (action, session) {
            let mut p = crate::script_command(include_str!("list_sessions.py"))?;
            p.arg(session);
            p
        } else {
            let mut p = crate::backend_command()?;
            p.arg(action);
            p
        };
        if action == "status" {
            if let Some(session) = session {
                process.args(["-s", session]);
            }
        }
        let output = process.output()?;
        use std::io::Write;
        std::io::stdout().write_all(&output.stdout)?;
        std::io::stderr().write_all(&output.stderr)?;
        if !output.status.success() {
            failed = true;
            eprintln!("Could not list sessions for {email}; continuing with other accounts.");
        }
    }
    if failed {
        bail!("Some accounts could not be queried; their sessions may still be running.");
    }
    Ok(())
}

pub fn profiles(filter: Option<&str>) -> Result<Vec<(String, PathBuf)>> {
    let data = registry()?;
    let accounts = data["accounts"]
        .as_object()
        .context("Invalid account registry")?;
    let mut result = Vec::new();
    for (email, item) in accounts {
        if filter.is_some_and(|f| !f.eq_ignore_ascii_case(email)) {
            continue;
        }
        let id = item["id"].as_str().context("Missing account profile ID")?;
        uuid::Uuid::parse_str(id)?;
        result.push((email.clone(), root()?.join("accounts").join(id)));
    }
    if filter.is_some() && result.is_empty() {
        bail!("Account is not saved. Run Colab auth login --account EMAIL.");
    }
    if result.is_empty() {
        result.push((String::new(), root()?));
    }
    Ok(result)
}
