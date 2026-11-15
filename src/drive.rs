use anyhow::{bail, Context, Result};
use std::{
    fs,
    os::fd::AsFd,
    path::{Path, PathBuf},
    process::Stdio,
};
fn preference(session: &str) -> Result<PathBuf> {
    let id = uuid::Uuid::new_v5(&uuid::Uuid::NAMESPACE_URL, session.as_bytes())
        .simple()
        .to_string();
    Ok(crate::accounts::profile()?
        .join("drive")
        .join(format!("{id}.enabled")))
}
fn mounted(socket: &Path) -> Result<bool> {
    Ok(crate::transport::client(socket)
        .args([
            "-T",
            "root@colab-runtime",
            "mountpoint -q /root/.Colab/drive && test -d /root/.Colab/drive/MyDrive",
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
    let prepare = format!(
        "python3 -c {}",
        crate::quote(include_str!("drive_backend.py"))
    );
    let output = crate::transport::client(socket)
        .args(["-T", "root@colab-runtime", &prepare])
        .stdin(Stdio::null())
        .output()?;
    if !output.status.success() {
        bail!("{}", String::from_utf8_lossy(&output.stderr).trim());
    }
    if String::from_utf8_lossy(&output.stdout).trim() == "mounted" {
        return Ok(());
    }
    eprintln!("Restoring Google Drive connection for {session}...");
    let stderr = std::io::stderr().as_fd().try_clone_to_owned()?;
    let status = crate::backend_command()?
        .args(["drivemount", "-s", session, "/root/.Colab/drive"])
        // Consent can use /dev/tty; never consume stdin intended for a program.
        .stdin(Stdio::null())
        .stdout(Stdio::from(stderr))
        .status()?;
    if !status.success() || !mounted(socket)? {
        bail!("Google Drive is not mounted. Complete Google's consent using `Colab drive mount --account EMAIL -s {session}` before retrying; no transfer was started.")
    }
    Ok(())
}
pub fn restore(socket: &Path, session: &str) -> Result<()> {
    if preference(session)?.exists() {
        mount_on(socket, session)?;
    }
    Ok(())
}
pub fn ready(session: &str) -> Result<PathBuf> {
    let socket = crate::transport::connect(session)?;
    mount_on(&socket, session)?;
    let path = preference(session)?;
    fs::create_dir_all(path.parent().context("Drive preference parent")?)?;
    fs::write(path, b"restore Google Drive when reconnecting\n")?;
    Ok(socket)
}
