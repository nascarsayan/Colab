use anyhow::{bail, Context, Result};
use std::{env, fs, os::unix::fs::PermissionsExt, path::PathBuf, process::Command};
const BACKEND: &str = "google-colab-cli==0.8.0";
const UV_INSTALLER: &str = "https://astral.sh/uv/0.13.7/install.sh";

pub fn prepare_path() -> Result<()> {
    let home = PathBuf::from(env::var_os("HOME").context("HOME is unset")?);
    let mut paths: Vec<_> = env::split_paths(&env::var_os("PATH").unwrap_or_default()).collect();
    for dir in [home.join(".local/bin"), home.join(".cargo/bin")] {
        if !paths.contains(&dir) {
            paths.push(dir);
        }
    }
    env::set_var("PATH", env::join_paths(paths)?);
    Ok(())
}
fn installed_version() -> Option<String> {
    let interpreter = crate::backend_interpreter().ok()?;
    let result = Command::new(interpreter)
        .args([
            "-c",
            "import importlib.metadata; print(importlib.metadata.version('google-colab-cli'))",
        ])
        .output()
        .ok()?;
    if !result.status.success() {
        return None;
    }
    Some(String::from_utf8_lossy(&result.stdout).trim().to_owned())
}
fn install_uv() -> Result<()> {
    let curl = crate::find_executable("curl")
        .context("Install curl or uv first, then rerun Colab setup")?;
    let temp = env::temp_dir().join(format!("Colab-setup-{}", uuid::Uuid::new_v4()));
    fs::create_dir(&temp)?;
    fs::set_permissions(&temp, fs::Permissions::from_mode(0o700))?;
    let result = (|| -> Result<()> {
        let script = temp.join("uv-install.sh");
        eprintln!("Installing uv from Astral's official installer...");
        let status = Command::new(curl)
            .args([
                "--fail",
                "--location",
                "--silent",
                "--show-error",
                "--proto",
                "=https",
                "--tlsv1.2",
                "--output",
            ])
            .arg(&script)
            .arg(UV_INSTALLER)
            .status()?;
        if !status.success() {
            bail!("Could not download uv installer ({status})")
        }
        let home = PathBuf::from(env::var_os("HOME").context("HOME is unset")?);
        let status = Command::new("/bin/sh")
            .arg(script)
            .env("UV_NO_MODIFY_PATH", "1")
            .env("UV_INSTALL_DIR", home.join(".local/bin"))
            .status()?;
        if !status.success() {
            bail!("uv installation failed ({status})")
        }
        Ok(())
    })();
    let _ = fs::remove_dir_all(temp);
    result?;
    if crate::find_executable("uv").is_none() {
        bail!("uv installer finished but uv is not available in ~/.local/bin")
    }
    Ok(())
}
pub fn login(no_browser: bool) -> Result<()> {
    let mut process = Command::new(crate::backend_interpreter()?);
    process.args(["-c", include_str!("login.py")]);
    if no_browser {
        process.arg("--no-browser");
    }
    crate::finish(process.status().context("starting guided Google login")?)
}
pub fn run(check: bool, skip_login: bool, no_browser: bool) -> Result<()> {
    let mut missing = Vec::new();
    for executable in ["ssh", "ssh-keygen"] {
        if let Some(path) = crate::find_executable(executable) {
            println!("{executable}: {}", path.display());
        } else {
            missing.push(executable);
        }
    }
    if !missing.is_empty() {
        bail!("Missing {}. Install OpenSSH client tools (Linux: sudo apt install openssh-client), then rerun setup.",missing.join(", "))
    }
    let mut version = installed_version();
    if check {
        if version.as_deref() != Some("0.8.0") {
            bail!("Google backend is missing or incompatible ({version:?}); run Colab setup")
        }
        println!("Google backend: 0.8.0\nPrerequisites ready. Login was not checked; use Colab login to verify it.");
        return Ok(());
    }
    if version.as_deref() != Some("0.8.0") {
        if crate::find_executable("uv").is_none() {
            install_uv()?;
        }
        let mut installer =
            Command::new(crate::find_executable("uv").context("uv is unavailable")?);
        installer.args(["tool", "install", "--python", "3.13", BACKEND]);
        let home = PathBuf::from(env::var_os("HOME").context("HOME is unset")?);
        installer.env("UV_TOOL_BIN_DIR", home.join(".config/Colab/backend/bin"));
        if crate::backend_interpreter().is_ok() {
            installer.arg("--force");
        }
        let status = installer
            .status()
            .context("installing the Google Colab backend")?;
        if !status.success() {
            bail!("Google backend installation failed ({status})")
        }
        version = installed_version();
    }
    if version.as_deref() != Some("0.8.0") {
        bail!("Google backend installation could not be verified; check uv tool list and PATH")
    }
    println!("Google backend: 0.8.0");
    crate::identity()?;
    if !skip_login {
        login(no_browser)?;
    } else {
        println!("Login skipped. Run Colab login when ready.");
    }
    println!("Setup complete. Create a runtime with: Colab create trainer --runtime t4");
    Ok(())
}
