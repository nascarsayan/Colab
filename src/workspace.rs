use anyhow::{bail, Context, Result};
use std::{
    fs,
    path::{Component, Path, PathBuf},
    process::Stdio,
};
#[derive(Clone)]
pub struct Config {
    pub remote: String,
    pub drive: String,
    pub local: Option<String>,
}
fn path(session: &str) -> Result<PathBuf> {
    let id = uuid::Uuid::new_v5(&uuid::Uuid::NAMESPACE_URL, session.as_bytes())
        .simple()
        .to_string();
    Ok(crate::accounts::profile()?
        .join("workspaces")
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
pub fn mount_path(input: Option<&str>, drive: &str) -> Result<String> {
    let leaf = Path::new(drive)
        .file_name()
        .and_then(|p| p.to_str())
        .context("Drive folder has no name")?;
    let input = input.unwrap_or(leaf);
    let path = if input.starts_with('/') {
        PathBuf::from(input)
    } else {
        PathBuf::from("/content").join(input)
    };
    let name = path
        .file_name()
        .and_then(|p| p.to_str())
        .context("Mount path must name a folder directly under /content")?;
    if path.parent() != Some(Path::new("/content"))
        || name.starts_with('.')
        || ["drive", "sample_data"].contains(&name)
        || input.contains('\0')
        || input.split('/').any(|s| [".", ".."].contains(&s))
    {
        bail!(
            "Mount path must be a non-reserved folder directly under /content, e.g. /content/Code"
        );
    }
    Ok(path.to_str().context("Mount path is not UTF-8")?.to_owned())
}
pub fn options(drive: Option<&str>, mount: Option<&str>, local: Option<&Path>) -> Result<Config> {
    let drive = remote_path(drive.unwrap_or("~/Code"))?;
    let remote = mount_path(mount, &drive)?;
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
    Ok(Config {
        remote,
        drive,
        local,
    })
}
pub fn save(session: &str, cfg: &Config) -> Result<()> {
    let file = path(session)?;
    fs::create_dir_all(file.parent().context("Workspace settings directory")?)?;
    let temporary = file.with_extension(format!("{}.tmp", uuid::Uuid::new_v4()));
    fs::write(
        &temporary,
        serde_json::to_vec_pretty(
            &serde_json::json!({"drive_path":cfg.drive.strip_prefix("/content/drive/MyDrive/").map(|tail| format!("~/{tail}")).unwrap_or_else(|| cfg.drive.clone()),"mount_path":cfg.remote,"local_dir":cfg.local}),
        )?,
    )?;
    fs::rename(temporary, file)?;
    Ok(())
}
pub fn load(session: &str) -> Result<Config> {
    let file = path(session)?;
    if !file.exists() {
        return options(None, None, None);
    }
    let value: serde_json::Value = serde_json::from_slice(&fs::read(file)?)?;
    let drive = remote_path(value["drive_path"].as_str().unwrap_or("~/Code"))?;
    let cfg = Config {
        remote: mount_path(value["mount_path"].as_str(), &drive)?,
        drive,
        local: value["local_dir"].as_str().map(str::to_owned),
    };
    if !value["mount_path"].is_string() {
        save(session, &cfg)?;
    }
    Ok(cfg)
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
        "python3 -c {} {} {}",
        crate::quote(include_str!("workspace_mount.py")),
        crate::quote(&cfg.drive),
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
    #[test]
    fn visible_mount_is_directly_under_content() {
        assert_eq!(
            mount_path(None, "/content/drive/MyDrive/Code").unwrap(),
            "/content/Code"
        );
        assert_eq!(
            mount_path(None, "/content/drive/MyDrive/Projects/Test").unwrap(),
            "/content/Test"
        );
        assert_eq!(
            mount_path(Some("Work"), "/content/drive/MyDrive/Code").unwrap(),
            "/content/Work"
        );
        for path in [
            "/tmp/Code",
            "/content/nested/Code",
            "../Code",
            "/content/../Code",
            "/content/drive",
            "/content/.hidden",
        ] {
            assert!(
                mount_path(Some(path), "/content/drive/MyDrive/Code").is_err(),
                "{path}"
            );
        }
    }
}
