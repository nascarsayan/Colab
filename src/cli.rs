//! Public command hierarchy. Hidden flat aliases map to the same operations.
use crate::{parse_dims, parse_name, Runtime};
use clap::{Args, Parser, Subcommand};
use std::path::PathBuf;

#[derive(Parser)]
#[command(
    version,
    about = "Manage Colab session list, run GPU code, and synchronize files"
)]
pub(crate) struct Cli {
    #[arg(short,long,global=true,value_parser=parse_name)]
    pub session: Option<String>,
    /// Skip the configured PC-to-Colab sync for this operation.
    #[arg(long, global = true)]
    pub no_auto_sync: bool,
    #[command(subcommand)]
    pub command: Tree,
}
#[derive(Subcommand)]
pub(crate) enum Tree {
    /// Install dependencies and guide initial Google login.
    Setup(SetupArgs),
    /// Google account authentication.
    Auth {
        #[command(subcommand)]
        command: AuthCommand,
    },
    /// Create, connect to, inspect, and stop runtimes.
    Session {
        #[command(subcommand)]
        command: SessionCommand,
    },
    /// Copy files and synchronize local/remote folders.
    #[command(alias = "file")]
    Files {
        #[command(subcommand)]
        command: FilesCommand,
    },
    /// Google Drive mount and workspace access.
    Drive {
        #[command(subcommand)]
        command: DriveCommand,
    },
    /// Execute a remote shell command with forwarded input/output.
    Exec(ExecArgs),
    /// Upload, compile, and execute a local program.
    Run(RunArgs),
    // Compatibility aliases stay out of the public help tree.
    #[command(hide = true)]
    Login(LoginArgs),
    #[command(hide = true)]
    Create(CreateArgs),
    #[command(hide = true)]
    Start(StartArgs),
    #[command(hide = true)]
    Attach(AttachArgs),
    #[command(hide = true)]
    Shell,
    #[command(hide = true)]
    Cp(CopyArgs),
    #[command(hide = true)]
    Sync(SyncArgs),
    #[command(hide = true)]
    SyncTargets(TargetArgs),
    #[command(hide = true)]
    MountDrive,
    #[command(hide = true)]
    Status,
    #[command(hide = true)]
    Sessions,
    #[command(hide = true)]
    Stop,
    #[command(hide = true)]
    Disconnect,
    #[command(hide = true)]
    Url(UrlArgs),
}
#[derive(Subcommand)]
pub(crate) enum AuthCommand {
    /// Sign in or verify cached credentials; opens Google consent when needed.
    Login(LoginArgs),
}
#[derive(Subcommand)]
pub(crate) enum SessionCommand {
    /// Allocate an independent runtime; omit NAME for a generated name.
    Create(CreateArgs),
    /// Prepare/recover a runtime without entering an interactive shell.
    Start(StartArgs),
    /// Open an interactive shell in the session's synchronized Drive workspace.
    Connect,
    /// Close the PC's shared SSH connection; leave the runtime running.
    Disconnect,
    /// Terminate the runtime and release its resources.
    Stop,
    /// List the account's active runtimes.
    List,
    /// Show hardware and state for the selected runtime.
    Status,
    /// Adopt an existing runtime by its backend endpoint.
    Attach(AttachArgs),
    /// Print or open the selected runtime's notebook URL.
    Url(UrlArgs),
}
#[derive(Subcommand)]
pub(crate) enum FilesCommand {
    /// Recursively copy between a local path and colab:/absolute/path.
    #[command(alias = "cp")]
    Copy(CopyArgs),
    /// Synchronize folders using a quoted '>', '<', or '<>' direction.
    Sync(SyncArgs),
    /// List remembered sync pairs offline.
    Targets(TargetArgs),
}
#[derive(Subcommand)]
pub(crate) enum DriveCommand {
    /// Mount/reuse Google Drive and prepare the session's working folder.
    Mount,
}
#[derive(Args)]
pub(crate) struct SetupArgs {
    #[arg(long, conflicts_with = "skip_login")]
    check: bool,
    #[arg(long)]
    skip_login: bool,
    #[arg(long)]
    no_browser: bool,
}
#[derive(Args)]
pub(crate) struct LoginArgs {
    #[arg(long)]
    no_browser: bool,
}
#[derive(Args)]
pub(crate) struct CreateArgs {
    #[arg(value_parser=parse_name)]
    name: Option<String>,
    /// Working folder in Google Drive; ~/ refers to My Drive.
    #[arg(long, default_value = "~/Code")]
    drive_path: String,
    /// PC folder to push into the workspace before operations.
    #[arg(long)]
    local_dir: Option<PathBuf>,
    #[arg(long, value_enum, ignore_case = true, default_value = "t4")]
    runtime: Runtime,
    #[arg(long)]
    high_mem: bool,
}
#[derive(Args)]
pub(crate) struct StartArgs {
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
}
#[derive(Args)]
pub(crate) struct AttachArgs {
    #[arg(long)]
    endpoint: Option<String>,
    #[arg(long, default_value = "T4")]
    gpu: String,
}
#[derive(Args)]
pub(crate) struct ExecArgs {
    #[arg(required = true, trailing_var_arg = true, allow_hyphen_values = true)]
    command: Vec<String>,
}
#[derive(Args)]
pub(crate) struct RunArgs {
    file: PathBuf,
    #[arg(long, default_value = "main")]
    entry: String,
    #[arg(long,default_value="1,1,1",value_parser=parse_dims)]
    grid: String,
    #[arg(long,default_value="1,1,1",value_parser=parse_dims)]
    block: String,
    #[arg(last = true)]
    args: Vec<String>,
}
#[derive(Args)]
pub(crate) struct CopyArgs {
    src: String,
    dest: String,
    #[arg(long)]
    dry_run: bool,
}
#[derive(Args)]
pub(crate) struct SyncArgs {
    src: String,
    direction: String,
    dest: String,
    #[arg(long)]
    dry_run: bool,
}
#[derive(Args)]
pub(crate) struct TargetArgs {
    #[arg(long)]
    all_sessions: bool,
    #[arg(long)]
    json: bool,
}
#[derive(Args)]
pub(crate) struct UrlArgs {
    #[arg(long)]
    open: bool,
}

// The execution layer has no knowledge of public spellings or aliases.
pub(crate) enum Operation {
    Setup {
        check: bool,
        skip_login: bool,
        no_browser: bool,
    },
    Login {
        no_browser: bool,
    },
    Create {
        name: Option<String>,
        drive_path: String,
        local_dir: Option<PathBuf>,
        runtime: Runtime,
        high_mem: bool,
    },
    Start {
        runtime: Option<Runtime>,
        gpu: Option<Runtime>,
        high_mem: bool,
    },
    Attach {
        endpoint: Option<String>,
        gpu: String,
    },
    Exec {
        command: Vec<String>,
    },
    Shell,
    Run {
        file: PathBuf,
        entry: String,
        grid: String,
        block: String,
        args: Vec<String>,
    },
    Cp {
        src: String,
        dest: String,
        dry_run: bool,
    },
    Sync {
        src: String,
        direction: String,
        dest: String,
        dry_run: bool,
    },
    SyncTargets {
        all_sessions: bool,
        json: bool,
    },
    MountDrive,
    Status,
    Sessions,
    Stop,
    Disconnect,
    Url {
        open: bool,
    },
}
impl Tree {
    pub fn operation(self) -> Operation {
        use Operation as O;
        match self {
            Self::Auth {
                command: AuthCommand::Login(a),
            } => Self::Login(a).operation(),
            Self::Session { command } => match command {
                SessionCommand::Create(a) => Self::Create(a).operation(),
                SessionCommand::Start(a) => Self::Start(a).operation(),
                SessionCommand::Connect => O::Shell,
                SessionCommand::Disconnect => O::Disconnect,
                SessionCommand::Stop => O::Stop,
                SessionCommand::List => O::Sessions,
                SessionCommand::Status => O::Status,
                SessionCommand::Attach(a) => Self::Attach(a).operation(),
                SessionCommand::Url(a) => Self::Url(a).operation(),
            },
            Self::Files { command } => match command {
                FilesCommand::Copy(a) => Self::Cp(a).operation(),
                FilesCommand::Sync(a) => Self::Sync(a).operation(),
                FilesCommand::Targets(a) => Self::SyncTargets(a).operation(),
            },
            Self::Drive {
                command: DriveCommand::Mount,
            } => O::MountDrive,
            Self::Setup(a) => O::Setup {
                check: a.check,
                skip_login: a.skip_login,
                no_browser: a.no_browser,
            },
            Self::Login(a) => O::Login {
                no_browser: a.no_browser,
            },
            Self::Create(a) => O::Create {
                name: a.name,
                drive_path: a.drive_path,
                local_dir: a.local_dir,
                runtime: a.runtime,
                high_mem: a.high_mem,
            },
            Self::Start(a) => O::Start {
                runtime: a.runtime,
                gpu: a.gpu,
                high_mem: a.high_mem,
            },
            Self::Attach(a) => O::Attach {
                endpoint: a.endpoint,
                gpu: a.gpu,
            },
            Self::Exec(a) => O::Exec { command: a.command },
            Self::Run(a) => O::Run {
                file: a.file,
                entry: a.entry,
                grid: a.grid,
                block: a.block,
                args: a.args,
            },
            Self::Cp(a) => O::Cp {
                src: a.src,
                dest: a.dest,
                dry_run: a.dry_run,
            },
            Self::Sync(a) => O::Sync {
                src: a.src,
                direction: a.direction,
                dest: a.dest,
                dry_run: a.dry_run,
            },
            Self::SyncTargets(a) => O::SyncTargets {
                all_sessions: a.all_sessions,
                json: a.json,
            },
            Self::Shell => O::Shell,
            Self::MountDrive => O::MountDrive,
            Self::Status => O::Status,
            Self::Sessions => O::Sessions,
            Self::Stop => O::Stop,
            Self::Disconnect => O::Disconnect,
            Self::Url(a) => O::Url { open: a.open },
        }
    }
}
