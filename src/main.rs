#![allow(non_snake_case)] // The executable is intentionally named Colab.
use anyhow::{bail, Context, Result};
use clap::{Parser, ValueEnum};
use fs2::FileExt;
use std::{
    ffi::OsStr,
    io::IsTerminal,
    path::{Path, PathBuf},
    process::{Command as Process, ExitStatus},
};

mod cli;
use cli::{Cli, Operation as Command};
#[derive(Clone, Copy, ValueEnum)]
pub(crate) enum Runtime {
    Cpu,
    T4,
    L4,
    G4,
    H100,
    A100,
    #[value(name = "v5e1", alias = "v5e-1")]
    V5e1,
    #[value(name = "v6e1", alias = "v6e-1")]
    V6e1,
}
impl Runtime {
    fn backend(self) -> &'static str {
        match self {
            Self::Cpu => "NONE",
            Self::T4 => "T4",
            Self::L4 => "L4",
            Self::G4 => "G4",
            Self::H100 => "H100",
            Self::A100 => "A100",
            Self::V5e1 => "V5E1",
            Self::V6e1 => "V6E1",
        }
    }
}
fn parse_name(name: &str) -> Result<String, String> {
    if name.is_empty()
        || name.len() > 64
        || !name
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || "-_.".contains(c))
    {
        return Err(
            "Use 1..64 letters, digits, dots, underscores, or hyphens for a session name".into(),
        );
    }
    Ok(name.into())
}
fn parse_dims(s: &str) -> Result<String, String> {
    let v = s
        .split(',')
        .map(str::parse::<u32>)
        .collect::<Result<Vec<_>, _>>()
        .map_err(|_| "Expected X,Y,Z")?;
    if v.len() != 3 || v.contains(&0) {
        return Err("Expected three positive dimensions: X,Y,Z".into());
    }
    Ok(s.into())
}
fn quote(s: &str) -> String {
    format!("'{}'", s.replace('\'', "'\\''"))
}
fn finish(status: ExitStatus) -> Result<()> {
    if !status.success() {
        std::process::exit(status.code().unwrap_or(1))
    }
    Ok(())
}
fn backend<I, S>(args: I) -> Result<()>
where
    I: IntoIterator<Item = S>,
    S: AsRef<OsStr>,
{
    finish(
        backend_command()?.args(args).status().context(
            "Run `uv tool install google-colab-cli==0.8.0` to install the Google backend",
        )?,
    )
}
fn identity() -> Result<PathBuf> {
    let base = std::env::var_os("HOME").context("HOME is unset")?;
    let dir = Path::new(&base).join(".config/Colab");
    std::fs::create_dir_all(&dir)?;
    let key = dir.join("id_ed25519");
    if !key.exists() {
        finish(
            Process::new("ssh-keygen")
                .args(["-q", "-t", "ed25519", "-N", ""])
                .arg("-f")
                .arg(&key)
                .status()
                .context("ssh-keygen is required")?,
        )?;
    }
    Ok(key)
}
mod drive;
mod runtimes;
mod sessions;
mod setup;
mod shell;
mod targets;
mod transport;
mod workspace;
fn execute_on(socket: &Path, cwd: &str, command: Option<&str>) -> Result<()> {
    let remote = format!(
        "cd {} && export PATH=/usr/local/cuda/bin:/usr/local/bin:/usr/bin:/bin:$PATH && {{\n{}\n}}",
        quote(cwd),
        command.unwrap_or("exec bash -i")
    );
    let tty = std::io::stdin().is_terminal() && std::io::stdout().is_terminal();
    let status = transport::client(socket)
        .arg(if tty { "-t" } else { "-T" })
        .args(["root@colab-runtime", &remote])
        .status()
        .context("opening a remote command channel")?;
    finish(status)
}
fn ssh(session: &str, command: Option<&str>, auto_sync: bool) -> Result<()> {
    let (socket, cwd) = workspace::prepare(session, auto_sync)?;
    let shell_command = shell::command(session);
    execute_on(&socket, &cwd, Some(command.unwrap_or(&shell_command)))
}
fn find_executable(name: &str) -> Option<PathBuf> {
    use std::os::unix::fs::PermissionsExt;
    std::env::split_paths(&std::env::var_os("PATH").unwrap_or_default())
        .map(|dir| dir.join(name))
        .find(|path| {
            path.is_file()
                && path
                    .metadata()
                    .map(|m| m.permissions().mode() & 0o111 != 0)
                    .unwrap_or(false)
        })
}
fn backend_interpreter() -> Result<PathBuf> {
    // The public backend launcher collides with Colab on case-insensitive filesystems.
    let home = PathBuf::from(std::env::var_os("HOME").context("HOME is unset")?);
    let mut candidates = vec![home.join(".config/Colab/backend/bin/colab")];
    if let Some(path) = find_executable("colab-backend") {
        candidates.push(path);
    }
    candidates.push(home.join(".local/share/uv/tools/google-colab-cli/bin/colab"));
    if let Some(path) = find_executable("colab") {
        candidates.push(path);
    }
    for executable in candidates {
        if let Ok(script) = std::fs::read_to_string(executable) {
            if let Some(interpreter) = script
                .lines()
                .next()
                .and_then(|s| s.strip_prefix("#!"))
                .map(str::trim)
                .filter(|s| Path::new(s).is_absolute() && Path::new(s).is_file())
            {
                return Ok(PathBuf::from(interpreter));
            }
        }
    }
    bail!("Google backend not installed; run Colab setup")
}
const BACKEND_CLI: &str =
    "from colab_cli.cli import app\napp.pretty_exceptions_enable=False\napp(standalone_mode=False)";
fn script_command(source: &str) -> Result<Process> {
    let mut command = Process::new(backend_interpreter()?);
    command.args(["-c", include_str!("runner.py"), source]);
    Ok(command)
}
fn backend_command() -> Result<Process> {
    let mut command = script_command(BACKEND_CLI)?;
    command.args(["--auth", "oauth2"]);
    Ok(command)
}

fn ensure(action: &str, session: &str, runtime: &str, endpoint: Option<&str>) -> Result<()> {
    manage(action, session, runtime, endpoint, None)
}
fn manage(
    action: &str,
    session: &str,
    runtime: &str,
    endpoint: Option<&str>,
    high_mem: Option<bool>,
) -> Result<()> {
    // Serialize allocation and registry updates across all local session names.
    let home = std::env::var_os("HOME").context("HOME is unset")?;
    let dir = Path::new(&home).join(".config/Colab");
    std::fs::create_dir_all(&dir)?;
    let guard = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(dir.join("allocation.lock"))?;
    guard.lock_exclusive()?;
    let mut p = script_command(include_str!("backend.py"))?;
    p.args([
        action,
        session,
        runtime,
        endpoint.unwrap_or(""),
        match high_mem {
            Some(true) => "true",
            Some(false) => "false",
            None => "",
        },
    ]);
    finish(p.status().context("running Colab session recovery")?)
}
fn transfer(
    session: &str,
    action: &str,
    src: &str,
    direction: &str,
    dest: &str,
    dry_run: bool,
    auto_sync: bool,
) -> Result<()> {
    let remote_paths: Vec<&str> = [src, dest]
        .iter()
        .filter_map(|p| {
            p.strip_prefix("colab:")
                .or_else(|| p.strip_prefix("collab:"))
        })
        .collect();
    if remote_paths.len() != 1 {
        bail!("Exactly one endpoint must use colab:/absolute/path")
    }
    if !remote_paths[0].starts_with('/') {
        bail!("Remote paths must be absolute, for example colab:/content/data")
    }
    let (socket, _) = workspace::prepare(session, auto_sync)?;
    transfer_on(&socket, session, action, src, direction, dest, dry_run)
}
fn transfer_on(
    socket: &Path,
    session: &str,
    action: &str,
    src: &str,
    direction: &str,
    dest: &str,
    dry_run: bool,
) -> Result<()> {
    let home = std::env::var_os("HOME").context("HOME is unset")?;
    let state = Path::new(&home).join(".config/Colab");
    let status = script_command(include_str!("files.py"))?
        .arg(include_str!("file_rpc.py"))
        .arg(socket)
        .arg(state)
        .args([
            session,
            action,
            src,
            direction,
            dest,
            if dry_run { "1" } else { "0" },
        ])
        .status()
        .context("running recursive file transfer")?;
    finish(status)
}
fn main() {
    if let Err(error) = run() {
        eprintln!("Error: {error:#}");
        std::process::exit(1);
    }
}
fn run() -> Result<()> {
    setup::prepare_path()?;
    let c = Cli::parse();
    let command = c.command.operation();
    let explicit = c.session.as_deref();
    let auto_sync = !c.no_auto_sync;
    // Selection is deliberately skipped for setup/login/listing and explicit creation.
    let selected = match &command {
        Command::Setup { .. }
        | Command::Login { .. }
        | Command::Sessions
        | Command::RuntimeList { .. }
        | Command::Create { .. }
        | Command::SyncTargets { .. } => String::new(),
        Command::Attach { .. } => explicit
            .map(str::to_owned)
            .map(Ok)
            .unwrap_or_else(sessions::generated)?,
        Command::Disconnect => match sessions::select(explicit, false) {
            Ok(name) => name,
            Err(error) => {
                if let Some(name) = sessions::local_first()? {
                    eprintln!("Could not check active sessions ({error}); disconnecting locally recorded session {name}.");
                    name
                } else {
                    return Err(error);
                }
            }
        },
        _ => sessions::select(
            explicit,
            matches!(&command, Command::Start { .. } | Command::Attach { .. }),
        )?,
    };
    let s = selected.as_str();
    match command {
        Command::Setup {
            check,
            skip_login,
            no_browser,
        } => setup::run(check, skip_login, no_browser),
        Command::Login { no_browser } => setup::login(no_browser),
        Command::RuntimeList { json } => runtimes::list(json),
        Command::Create {
            name,
            runtime,
            high_mem,
            drive_path,
            local_dir,
        } => {
            let name = name
                .or_else(|| explicit.map(str::to_owned))
                .map(Ok)
                .unwrap_or_else(sessions::generated)?;
            let cfg = workspace::options(Some(&drive_path), local_dir.as_deref())?;
            manage("create", &name, runtime.backend(), None, Some(high_mem))?;
            workspace::save(&name, &cfg)?;
            workspace::prepare(&name, auto_sync).with_context(||format!("Session {name} was created, but its workspace is not ready. Run Colab drive mount -s {name} to finish setup"))?;
            println!("Session {name} ready in {}", cfg.remote);
            Ok(())
        }
        Command::Start {
            runtime,
            gpu,
            high_mem,
        } => {
            manage(
                "start",
                s,
                runtime.or(gpu).map(Runtime::backend).unwrap_or(""),
                None,
                if high_mem { Some(true) } else { None },
            )?;
            workspace::prepare(s, auto_sync)?;
            Ok(())
        }
        Command::Attach { endpoint, gpu } => {
            ensure("attach", s, &gpu, endpoint.as_deref())?;
            workspace::prepare(s, auto_sync)?;
            Ok(())
        }
        Command::Exec { command } => {
            // A single argument is a shell line; multiple arguments are an exact argv.
            let line = if command.len() == 1 {
                command[0].clone()
            } else {
                command
                    .iter()
                    .map(|x| quote(x))
                    .collect::<Vec<_>>()
                    .join(" ")
            };
            ssh(s, Some(&line), auto_sync)
        }
        Command::Shell => ssh(s, None, auto_sync),
        Command::SyncTargets { all_sessions, json } => targets::list(
            explicit.unwrap_or(""),
            all_sessions || explicit.is_none(),
            json,
        ),
        Command::MountDrive => {
            let (_, cwd) = workspace::prepare(s, auto_sync)?;
            println!("Google Drive workspace ready: {cwd}");
            Ok(())
        }
        Command::Cp { src, dest, dry_run } => {
            transfer(s, "cp", &src, ">", &dest, dry_run, auto_sync)
        }
        Command::Sync {
            src,
            direction,
            dest,
            dry_run,
        } => {
            if ![">", "<", "<>"].contains(&direction.as_str()) {
                bail!("Direction must be quoted: '>', '<', or '<>'")
            }
            transfer(s, "sync", &src, &direction, &dest, dry_run, auto_sync)
        }
        Command::Status => backend(["status", "-s", s]),
        Command::Sessions => backend(["sessions"]),
        Command::Stop => {
            transport::disconnect(s)?;
            backend(["stop", "-s", s])
        }
        Command::Disconnect => transport::disconnect(s),
        Command::Url { open } => {
            let mut args = vec!["url", "-s", s];
            if open {
                args.push("--open")
            }
            backend(args)
        }
        Command::Run {
            file,
            entry,
            grid,
            block,
            args,
        } => {
            if !file.is_file() {
                bail!("Source file not found: {}", file.display())
            }
            let ext = file
                .extension()
                .and_then(|s| s.to_str())
                .unwrap_or("")
                .to_ascii_lowercase();
            if !["cu", "c", "cc", "cpp", "cxx", "ptx", "sh"].contains(&ext.as_str()) {
                bail!("Unsupported source extension: {ext}")
            }
            let prefix = format!("/tmp/Colab-{}", uuid::Uuid::new_v4());
            let remote = format!("{prefix}.{ext}");
            // Recover an expired runtime before uploading to it.
            let (socket, cwd) = workspace::prepare(s, auto_sync)?;
            backend([
                OsStr::new("upload"),
                OsStr::new("-s"),
                OsStr::new(s),
                file.as_os_str(),
                OsStr::new(&remote),
            ])?;
            let argv = args.iter().map(|a| quote(a)).collect::<Vec<_>>().join(" ");
            let command = if ext == "sh" {
                format!("bash {} {argv}", quote(&remote))
            } else if ext == "ptx" {
                let code = include_str!("ptx.py");
                format!(
                    "python3 -c {} {} {} {} {}",
                    quote(code),
                    quote(&remote),
                    quote(&entry),
                    quote(&grid),
                    quote(&block)
                )
            } else {
                format!(
                    "nvcc -x cu {} -o {} && {} {argv}",
                    quote(&remote),
                    quote(&prefix),
                    quote(&prefix)
                )
            };
            execute_on(&socket, &cwd, Some(&command))
        }
    }
}
