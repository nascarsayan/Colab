#![allow(non_snake_case)] // The executable is intentionally named Colab.
use anyhow::{bail, Context, Result};
use clap::{Parser, Subcommand, ValueEnum};
use fs2::FileExt;
use std::{
    ffi::OsStr,
    io::IsTerminal,
    path::{Path, PathBuf},
    process::{Command as Process, ExitStatus},
};

#[derive(Parser)]
#[command(
    version,
    about = "Run GPU code and shell commands through Google's authenticated Colab backend"
)]
struct Cli {
    #[arg(short, long, global = true, default_value = "gpu-proxy", value_parser = parse_name)]
    session: String,
    #[command(subcommand)]
    command: Command,
}
#[derive(Subcommand)]
enum Command {
    /// Install prerequisites and guide Google login (does not allocate a runtime).
    Setup {
        #[arg(long, conflicts_with = "skip_login")]
        check: bool,
        #[arg(long)]
        skip_login: bool,
        #[arg(long)]
        no_browser: bool,
    },
    /// Google login: opens the browser, then accepts Google's authorization code.
    Login {
        #[arg(long)]
        no_browser: bool,
    },
    /// Create a new independent runtime; the session name is required.
    Create {
        #[arg(value_parser = parse_name)]
        name: String,
        #[arg(long, value_enum, ignore_case = true, default_value = "t4")]
        runtime: Runtime,
        #[arg(long)]
        high_mem: bool,
    },
    /// Reuse/recover a named session, or allocate an unclaimed runtime.
    Start {
        #[arg(long, value_enum, ignore_case = true, conflicts_with = "gpu")]
        runtime: Option<Runtime>,
        #[arg(
            long,
            value_enum,
            ignore_case = true,
            help = "Legacy alias for --runtime"
        )]
        gpu: Option<Runtime>,
        #[arg(long)]
        high_mem: bool,
    },
    /// Adopt an existing runtime, including one opened from a notebook.
    Attach {
        #[arg(long)]
        endpoint: Option<String>,
        #[arg(long, default_value = "T4")]
        gpu: String,
    },
    /// Execute a shell command remotely, forwarding stdin/stdout/stderr and exit status.
    Exec {
        #[arg(required = true, trailing_var_arg = true, allow_hyphen_values = true)]
        command: Vec<String>,
    },
    /// Open an interactive SSH terminal, recovering an expired runtime if needed.
    Shell,
    /// Upload, compile, and execute a CUDA, C/C++, shell, or PTX source file.
    Run {
        file: PathBuf,
        #[arg(long, default_value = "main")]
        entry: String,
        #[arg(long, default_value="1,1,1", value_parser=parse_dims)]
        grid: String,
        #[arg(long, default_value="1,1,1", value_parser=parse_dims)]
        block: String,
        #[arg(last = true)]
        args: Vec<String>,
    },
    /// Recursively copy between a local path and colab:/absolute/path.
    Cp {
        src: String,
        dest: String,
        #[arg(long)]
        dry_run: bool,
    },
    /// Sync directories: quote the direction operator: '>', '<', or '<>'.
    Sync {
        src: String,
        direction: String,
        dest: String,
        #[arg(long)]
        dry_run: bool,
    },
    /// List recorded sync pairs locally, without connecting to Google.
    SyncTargets {
        #[arg(long)]
        all_sessions: bool,
        #[arg(long)]
        json: bool,
    },
    /// Mount Google Drive at /content/drive, reusing an existing mount.
    MountDrive,
    Status,
    Sessions,
    Stop,
    /// Close the shared local SSH connection without stopping the GPU runtime.
    Disconnect,
    /// Print the runtime URL, optionally opening it in the browser.
    Url {
        #[arg(long)]
        open: bool,
    },
}
#[derive(Clone, Copy, ValueEnum)]
enum Runtime {
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
mod setup;
mod targets;
mod transport;
fn ssh(session: &str, command: Option<&str>) -> Result<()> {
    let socket = transport::connect(session)?;
    let remote = format!(
        "cd /content && export PATH=/usr/local/cuda/bin:/usr/local/bin:/usr/bin:/bin:$PATH; {}",
        command.unwrap_or("exec bash -i")
    );
    let tty = std::io::stdin().is_terminal() && std::io::stdout().is_terminal();
    let status = transport::client(&socket)
        .arg(if tty { "-t" } else { "-T" })
        .args(["root@colab-runtime", &remote])
        .status()
        .context("opening a channel on the shared Colab connection")?;
    // Never retry an executed command automatically: it may have had side effects.
    finish(status)
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
fn backend_command() -> Result<Process> {
    let mut command = Process::new(backend_interpreter()?);
    command.args(["-m", "colab_cli.cli", "--auth", "oauth2"]);
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
    let interpreter = backend_interpreter()?;
    let mut p = Process::new(interpreter);
    p.args([
        "-c",
        include_str!("backend.py"),
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
    // Never populate the ephemeral mount directory if Drive authorization failed.
    if [src, dest].iter().any(|p| {
        ["colab:/content/drive", "collab:/content/drive"]
            .iter()
            .any(|prefix| *p == *prefix || p.starts_with(&format!("{prefix}/")))
    }) {
        drive::mount(session)?;
    }
    let socket = transport::connect(session)?;
    let home = std::env::var_os("HOME").context("HOME is unset")?;
    let state = Path::new(&home).join(".config/Colab");
    let status = Process::new(backend_interpreter()?)
        .args(["-c", include_str!("files.py"), include_str!("file_rpc.py")])
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
fn main() -> Result<()> {
    setup::prepare_path()?;
    let c = Cli::parse();
    let s = &c.session;
    match c.command {
        Command::Setup {
            check,
            skip_login,
            no_browser,
        } => setup::run(check, skip_login, no_browser),
        Command::Login { no_browser } => setup::login(no_browser),
        Command::Create {
            name,
            runtime,
            high_mem,
        } => manage("create", &name, runtime.backend(), None, Some(high_mem)),
        Command::Start {
            runtime,
            gpu,
            high_mem,
        } => manage(
            "start",
            s,
            runtime.or(gpu).map(Runtime::backend).unwrap_or(""),
            None,
            if high_mem { Some(true) } else { None },
        ),
        Command::Attach { endpoint, gpu } => ensure("attach", s, &gpu, endpoint.as_deref()),
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
            ssh(s, Some(&line))
        }
        Command::Shell => ssh(s, None),
        Command::SyncTargets { all_sessions, json } => targets::list(s, all_sessions, json),
        Command::MountDrive => drive::mount(s),
        Command::Cp { src, dest, dry_run } => transfer(s, "cp", &src, ">", &dest, dry_run),
        Command::Sync {
            src,
            direction,
            dest,
            dry_run,
        } => {
            if ![">", "<", "<>"].contains(&direction.as_str()) {
                bail!("Direction must be quoted: '>', '<', or '<>'")
            }
            transfer(s, "sync", &src, &direction, &dest, dry_run)
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
            transport::connect(s)?;
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
            ssh(s, Some(&command))
        }
    }
}
