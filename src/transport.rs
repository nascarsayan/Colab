//! One SSH master per remote endpoint; local CLI calls open independent channels.
use anyhow::{bail, Context, Result};
use fs2::FileExt;
use std::{
    fs::{self, File, OpenOptions},
    os::unix::fs::{OpenOptionsExt, PermissionsExt},
    path::{Path, PathBuf},
    process::{Command, Stdio},
};

fn socket_path(session: &str) -> Result<PathBuf> {
    let home = PathBuf::from(std::env::var_os("HOME").context("HOME is unset")?);
    let state: serde_json::Value = serde_json::from_slice(
        &fs::read(home.join(".config/colab-cli/sessions.json"))
            .context("No Colab session state; run Colab start")?,
    )?;
    let endpoint = state
        .get(session)
        .and_then(|s| s.get("endpoint"))
        .and_then(|v| v.as_str())
        .context("Session not found; run Colab start")?;
    // Key by endpoint so aliases for the same runtime share one transport too.
    let id = uuid::Uuid::new_v5(&uuid::Uuid::NAMESPACE_URL, endpoint.as_bytes())
        .simple()
        .to_string();
    let dir = home.join(".config/Colab/mux");
    fs::create_dir_all(&dir)?;
    fs::set_permissions(&dir, fs::Permissions::from_mode(0o700))?;
    let socket = dir.join(format!("{id}.sock"));
    if socket.as_os_str().len() >= 100 {
        bail!("SSH control socket path is too long: {}", socket.display())
    }
    Ok(socket)
}
fn lock(socket: &Path) -> Result<File> {
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .open(socket.with_extension("lock"))?;
    file.lock_exclusive()?;
    Ok(file)
}
fn base(socket: &Path) -> Command {
    let mut p = Command::new("ssh");
    p.args(["-F", "/dev/null", "-S"])
        .arg(socket)
        .args(["-o", "LogLevel=ERROR"]);
    p
}
fn alive(socket: &Path) -> bool {
    socket.exists()
        && base(socket)
            .args(["-O", "check", "root@colab-runtime"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map(|s| s.success())
            .unwrap_or(false)
}
pub fn client(socket: &Path) -> Command {
    let mut p = base(socket);
    // A dead/missing master must fail rather than silently opening another transport.
    p.args(["-o", "ControlMaster=no", "-o", "ProxyCommand=false"]);
    p
}
fn session_lock(session: &str) -> Result<File> {
    let home = PathBuf::from(std::env::var_os("HOME").context("HOME is unset")?);
    let dir = home.join(".config/Colab/mux");
    fs::create_dir_all(&dir)?;
    fs::set_permissions(&dir, fs::Permissions::from_mode(0o700))?;
    let id = uuid::Uuid::new_v5(&uuid::Uuid::NAMESPACE_URL, session.as_bytes())
        .simple()
        .to_string();
    lock(&dir.join(format!("session-{id}")))
}
pub fn connect(session: &str) -> Result<PathBuf> {
    // Serialize recovery independently of the endpoint: it can change after expiry.
    let _session_guard = session_lock(session)?;
    if let Ok(socket) = socket_path(session) {
        if alive(&socket) {
            crate::drive::restore(&socket, session)?;
            return Ok(socket);
        }
    }
    // Validate against Google before opening a new transport; recreate only before
    // submitting any user command. Existing master channels stay on the fast path.
    crate::ensure("connect", session, "", None)?;
    let socket = socket_path(session)?;
    let _guard = lock(&socket)?;
    if alive(&socket) {
        crate::drive::restore(&socket, session)?;
        return Ok(socket);
    }
    if socket.exists() {
        fs::remove_file(&socket)?;
    }
    let key = crate::identity()?;
    let interpreter = crate::backend_interpreter()?;
    let proxy = [
        interpreter
            .to_str()
            .context("Backend interpreter path is not UTF-8")?,
        "-m",
        "colab_cli.cli",
        "--auth",
        "oauth2",
        "ssh",
        "--proxy-mode",
        "-s",
        session,
        "-i",
        key.to_str().context("SSH key path is not UTF-8")?,
        "--colab-internal-mode",
        "cmd",
    ]
    .iter()
    .map(|s| crate::quote(s))
    .collect::<Vec<_>>()
    .join(" ");
    let log_path = socket.with_extension("log");
    let log = OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .mode(0o600)
        .open(&log_path)?;
    let status = base(&socket)
        .args(["-M", "-fN", "-i"])
        .arg(&key)
        .args([
            "-o",
            "ControlPersist=600",
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=3",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            &format!("ProxyCommand={proxy}"),
            "root@colab-runtime",
        ])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::from(log))
        .status()
        .context("starting the shared Colab SSH connection")?;
    if !status.success() {
        let details = fs::read_to_string(&log_path).unwrap_or_default();
        let hint = if details.contains("429") {
            "Google rejected an additional SSH connection. Close standalone `colab ssh` connections and retry."
        } else {
            "The connection failed before your command was submitted. Run `Colab start` to check runtime availability and authentication."
        };
        bail!(
            "Could not establish shared SSH transport ({status}). {hint}\n{}\nDiagnostics: {}",
            details.trim(),
            log_path.display()
        )
    }
    if !alive(&socket) {
        bail!("SSH master did not create a usable control socket")
    }
    crate::drive::restore(&socket, session)?;
    Ok(socket)
}
pub fn disconnect(session: &str) -> Result<()> {
    let socket = socket_path(session)?;
    let _guard = lock(&socket)?;
    if alive(&socket) {
        let status = base(&socket)
            .args(["-O", "exit", "root@colab-runtime"])
            .status()?;
        if !status.success() {
            bail!("Could not close SSH master: {status}")
        }
    } else if socket.exists() {
        fs::remove_file(&socket)?;
    }
    Ok(())
}
