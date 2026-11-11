use anyhow::{bail, Context, Result};
use std::{
    fs,
    os::fd::AsFd,
    path::{Path, PathBuf},
    process::Stdio,
};
fn preference(session: &str) -> Result<PathBuf> {
    let home = PathBuf::from(std::env::var_os("HOME").context("HOME is unset")?);
    let id = uuid::Uuid::new_v5(&uuid::Uuid::NAMESPACE_URL, session.as_bytes())
        .simple()
        .to_string();
    Ok(home
        .join(".config/Colab/drive")
        .join(format!("{id}.enabled")))
}
fn mounted(socket: &Path) -> Result<bool> {
    Ok(crate::transport::client(socket)
        .args([
            "-T",
            "root@colab-runtime",
            "mountpoint -q /content/drive && test -d /content/drive/MyDrive",
        ])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .status()?
        .success())
}
fn mount_on(socket: &Path, session: &str) -> Result<()> {
    if mounted(socket)? {
        return Ok(());
    }
    eprintln!("Restoring Google Drive mount for {session}...");
    let stderr = std::io::stderr().as_fd().try_clone_to_owned()?;
    let status = crate::backend_command()?
        .args(["drivemount", "-s", session])
        .stdout(Stdio::from(stderr))
        .status()?;
    if !status.success() || !mounted(socket)? {
        bail!("Google Drive is not mounted. Complete Google's consent using `Colab mount-drive` before retrying; no transfer was started.")
    }
    Ok(())
}
pub fn restore(socket: &Path, session: &str) -> Result<()> {
    if preference(session)?.exists() {
        mount_on(socket, session)?;
    }
    Ok(())
}
pub fn mount(session: &str) -> Result<()> {
    let socket = crate::transport::connect(session)?;
    mount_on(&socket, session)?;
    let path = preference(session)?;
    fs::create_dir_all(path.parent().context("Drive preference parent")?)?;
    fs::write(path, b"restore Google Drive when reconnecting\n")?;
    eprintln!("Google Drive ready: /content/drive/MyDrive (automatic restoration enabled)");
    Ok(())
}
