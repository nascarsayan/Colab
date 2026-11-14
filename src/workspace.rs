use anyhow::{bail, Context, Result};
use std::{
    fs,
    path::{Component, Path, PathBuf},
    process::Stdio,
};
#[derive(Clone)]
pub struct Config {
    pub remote: String,
    pub local: Option<String>,
}
fn path(session: &str) -> Result<PathBuf> {
    let home = PathBuf::from(std::env::var_os("HOME").context("HOME is unset")?);
    let id = uuid::Uuid::new_v5(&uuid::Uuid::NAMESPACE_URL, session.as_bytes())
        .simple()
        .to_string();
    Ok(home
        .join(".config/Colab/workspaces")
        .join(format!("{id}.json")))
}
pub fn remote_path(input: &str) -> Result<String> {
    let tail = input
        .strip_prefix("/content/drive/MyDrive/")
        .or_else(|| input.strip_prefix("~/"))
        .or_else(|| input.strip_prefix("MyDrive/"))
        .unwrap_or(input);
    let out = if ["~", "/content/drive/MyDrive", "MyDrive"].contains(&input) {
        "/content/drive/MyDrive".into()
    } else if input.starts_with("/content/drive/") {
        input.to_owned()
    } else if !input.starts_with('/') {
        format!("/content/drive/MyDrive/{tail}")
    } else {
        bail!("Drive folder must be relative to My Drive (e.g. ~/Code), or an absolute path under /content/drive")
    };
    if Path::new(&out)
        .components()
        .any(|c| matches!(c, Component::ParentDir))
        || input.is_empty()
        || out.contains('\0')
    {
        bail!("Invalid Drive folder path")
    }
    Ok(out.trim_end_matches('/').to_owned())
}
pub fn options(drive: Option<&str>, local: Option<&Path>) -> Result<Config> {
    let remote = remote_path(drive.unwrap_or("~/Code"))?;
    let local = if let Some(p) = local {
        let text = p.to_string_lossy();
        let expanded = if let Some(tail) = text.strip_prefix("~/") {
            PathBuf::from(std::env::var_os("HOME").context("HOME is unset")?).join(tail)
        } else {
            p.to_owned()
        };
        if !expanded.is_dir() {
            bail!(
                "Local sync folder does not exist or is not a directory: {}",
                expanded.display()
            )
        }
        Some(
            expanded
                .canonicalize()?
                .to_str()
                .context("Local sync path is not UTF-8")?
                .to_owned(),
        )
    } else {
        None
    };
    Ok(Config { remote, local })
}
pub fn save(session: &str, cfg: &Config) -> Result<()> {
    let file = path(session)?;
    fs::create_dir_all(file.parent().context("Workspace settings directory")?)?;
    let temporary = file.with_extension(format!("{}.tmp", uuid::Uuid::new_v4()));
    fs::write(
        &temporary,
        serde_json::to_vec_pretty(
            &serde_json::json!({"drive_path":cfg.remote,"local_dir":cfg.local}),
        )?,
    )?;
    fs::rename(temporary, file)?;
    Ok(())
}
pub fn load(session: &str) -> Result<Config> {
    let file = path(session)?;
    if !file.exists() {
        return options(None, None);
    }
    let value: serde_json::Value = serde_json::from_slice(&fs::read(file)?)?;
    Ok(Config {
        remote: remote_path(value["drive_path"].as_str().unwrap_or("~/Code"))?,
        local: value["local_dir"].as_str().map(str::to_owned),
    })
}
pub fn prepare(session: &str, auto_sync: bool) -> Result<(PathBuf, String)> {
    let cfg = load(session)?;
    if auto_sync {
        if let Some(local) = &cfg.local {
            if !Path::new(local).is_dir() {
                bail!("Configured local sync folder is missing: {local}. Restore it or use --no-auto-sync; remote command was not started.")
            }
        }
    }
    let socket = crate::drive::ready(session)?;
    let command = format!(
        "mountpoint -q /content/drive && mkdir -p -- {} && test -d {}",
        crate::quote(&cfg.remote),
        crate::quote(&cfg.remote)
    );
    let status = crate::transport::client(&socket)
        .args(["-T", "root@colab-runtime", &command])
        .stdin(Stdio::null())
        .status()?;
    if !status.success() {
        bail!(
            "Could not prepare the Drive workspace {}; no command was started",
            cfg.remote
        )
    }
    if auto_sync {
        if let Some(local) = &cfg.local {
            eprintln!("Syncing {local} -> {}", cfg.remote);
            crate::transfer_on(
                &socket,
                session,
                "sync",
                local,
                ">",
                &format!("colab:{}", cfg.remote),
                false,
            )?;
        }
    }
    Ok((socket, cfg.remote))
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn drive_folder_normalization() {
        for p in [
            "~/Code",
            "Code",
            "MyDrive/Code",
            "/content/drive/MyDrive/Code",
        ] {
            assert_eq!(remote_path(p).unwrap(), "/content/drive/MyDrive/Code");
        }
        assert!(remote_path("../escape").is_err());
        assert!(remote_path("/tmp/not-drive").is_err());
    }
}
