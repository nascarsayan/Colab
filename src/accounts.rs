//! Account discovery, defaults, and aggregate operations share one verified registry.
use anyhow::{bail, Context, Result};
use serde_json::{json, Value};
use std::{env, fs, io::Write, path::PathBuf};

pub fn display(email: &str) -> &str {
    email.strip_suffix("@gmail.com").unwrap_or(email)
}
pub fn root() -> Result<PathBuf> {
    Ok(PathBuf::from(env::var_os("HOME").context("HOME is unset")?).join(".config/Colab"))
}
fn registry() -> Result<Value> {
    let path = root()?.join("accounts.json");
    if !path.exists() {
        return Ok(json!({"accounts": {}}));
    }
    let data: Value = serde_json::from_slice(&fs::read(path)?)?;
    if !data["accounts"].is_object() {
        bail!("Invalid account registry; restore ~/.config/Colab/accounts.json.");
    }
    Ok(data)
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
    let id = data["accounts"][&email]["id"].as_str().with_context(|| {
        format!(
            "Account {} is not saved. Run Colab auth login --account {}",
            display(&email),
            display(&email)
        )
    })?;
    uuid::Uuid::parse_str(id).context("Invalid account profile ID")?;
    env::set_var("COLAB_ACCOUNT", &email);
    env::set_var("COLAB_PROFILE_DIR", root()?.join("accounts").join(id));
    Ok(())
}
pub fn configure_login(email: Option<&str>) -> Result<()> {
    if let Some(email) = email {
        env::set_var("COLAB_LOGIN_EMAIL", email.to_lowercase());
    }
    Ok(())
}
/// Look for cached credentials only. Exit 3 means absent, rather than an auth failure.
pub fn recover(filter: Option<&str>) -> Result<bool> {
    let data = registry()?;
    let accounts = data["accounts"]
        .as_object()
        .context("Invalid account registry")?;
    if filter.is_none() && !accounts.is_empty()
        || filter.is_some_and(|e| accounts.contains_key(&e.to_lowercase()))
    {
        return Ok(true);
    }
    if filter.is_none() && data["legacy_signed_out"].as_bool() == Some(true) {
        return Ok(false);
    }
    crate::setup::ensure()?;
    let mut process = crate::script_command(include_str!("login.py"))?;
    process.arg("--cached").arg("--no-browser");
    if let Some(email) = filter {
        process.env("COLAB_LOGIN_EMAIL", email.to_lowercase());
    }
    let output = process.output()?;
    if output.status.code() == Some(3) {
        return Ok(false);
    }
    if !output.status.success() {
        bail!(
            "Could not check cached Google credentials: {}",
            String::from_utf8_lossy(&output.stderr)
                .trim()
                .trim_start_matches("Error: ")
        );
    }
    let updated = registry()?;
    Ok(updated["accounts"]
        .as_object()
        .is_some_and(|a| !a.is_empty()))
}
fn default_email(data: &Value) -> Option<&str> {
    data["default"]
        .as_str()
        .filter(|email| data["accounts"].get(*email).is_some())
        .or_else(|| {
            data["accounts"]
                .as_object()?
                .keys()
                .next()
                .map(String::as_str)
        })
}
pub fn select(email: Option<&str>, session: Option<&str>) -> Result<()> {
    recover(email)?;
    let data = registry()?;
    let selected = if let Some(email) = email {
        email.to_lowercase()
    } else if let Some(session) = session {
        let mut owners = Vec::new();
        for (email, path) in profiles(None)? {
            let path = path.join("sessions.json");
            if !email.is_empty() && path.exists() {
                let state: Value = serde_json::from_slice(&fs::read(path)?)?;
                if state.get(session).is_some() {
                    owners.push(email);
                }
            }
        }
        match owners.len() {
            1 => owners.remove(0),
            0 => default_email(&data).context("No saved Google account. Run Colab auth login.")?.to_owned(),
            _ => bail!("Session {session} exists in multiple accounts: {}. Select one with --account EMAIL.", owners.iter().map(|email| display(email)).collect::<Vec<_>>().join(", ")),
        }
    } else {
        default_email(&data)
            .context("No saved Google account. Run Colab auth login.")?
            .to_owned()
    };
    activate(&selected, &data)?;
    eprintln!("Account: {}", display(&selected));
    Ok(())
}
pub fn list(filter: Option<&str>) -> Result<()> {
    recover(filter)?;
    let data = registry()?;
    println!("DEFAULT  ACCOUNT");
    let accounts = data["accounts"]
        .as_object()
        .context("Invalid account registry")?;
    for email in accounts.keys() {
        if filter.is_some_and(|f| !f.eq_ignore_ascii_case(email)) {
            continue;
        }
        println!(
            "{:<7}  {}",
            if default_email(&data) == Some(email) {
                "*"
            } else {
                ""
            },
            display(email)
        );
    }
    if accounts.is_empty() {
        println!("No saved accounts. Run Colab auth login.");
    }
    Ok(())
}
pub fn set_default(email: &str) -> Result<()> {
    if !recover(Some(email))? {
        bail!(
            "Account {} is not saved. Run Colab auth login --account {}.",
            display(email),
            display(email)
        );
    }
    crate::setup::ensure()?;
    crate::finish(
        crate::script_command(include_str!("account_admin.py"))?
            .args(["default", &email.to_lowercase()])
            .status()?,
    )
}
fn inventory(name: Option<&str>) -> Result<Vec<Value>> {
    let output = crate::script_command(include_str!("list_sessions.py"))?
        .arg(name.unwrap_or(""))
        .output()?;
    if !output.status.success() {
        bail!(
            "{}",
            String::from_utf8_lossy(&output.stderr)
                .trim()
                .trim_start_matches("Error: ")
        );
    }
    let rows: Vec<Value> = serde_json::from_slice(&output.stdout)
        .context("Invalid session inventory returned by Google backend")?;
    if rows
        .iter()
        .any(|row| !row.is_object() || !row["endpoint"].is_string())
    {
        bail!("Invalid session inventory returned by Google backend");
    }
    Ok(rows)
}
fn cell(value: &Value, key: &str) -> String {
    value[key].as_str().unwrap_or("-").to_owned()
}
fn clean(text: &str) -> String {
    text.chars()
        .map(|c| if c.is_control() { ' ' } else { c })
        .collect()
}
fn short_path(path: &str) -> String {
    if let Some(tail) = path.strip_prefix("/content/drive/MyDrive") {
        return format!("MyDrive{tail}");
    }
    if let Some(home) = env::var_os("HOME") {
        if let Ok(tail) = std::path::Path::new(path).strip_prefix(&home) {
            return format!("~/{}", tail.display());
        }
    }
    path.to_owned()
}
fn terminal_width() -> usize {
    if let Some(width) = env::var("COLUMNS")
        .ok()
        .and_then(|s| s.parse::<usize>().ok())
        .filter(|w| *w > 0)
    {
        return width.min(1000);
    }
    use std::os::fd::AsRawFd;
    let mut size = libc::winsize {
        ws_row: 0,
        ws_col: 0,
        ws_xpixel: 0,
        ws_ypixel: 0,
    };
    // ioctl writes a winsize to this valid stack allocation; failure means stdout
    // is redirected or terminal geometry is unavailable.
    if unsafe { libc::ioctl(std::io::stdout().as_raw_fd(), libc::TIOCGWINSZ, &mut size) } == 0
        && size.ws_col > 0
    {
        return usize::from(size.ws_col);
    }
    120
}
fn text_width(text: &str) -> usize {
    unicode_width::UnicodeWidthStr::width(text)
}
fn fit(text: &str, width: usize) -> String {
    if text_width(text) <= width {
        return text.to_owned();
    }
    if width == 0 {
        return String::new();
    }
    let mut clipped = String::new();
    for ch in text.chars() {
        let mut next = clipped.clone();
        next.push(ch);
        if text_width(&next) > width - 1 {
            break;
        }
        clipped = next;
    }
    clipped.push('…');
    clipped
}
fn table(headers: &[&str], rows: &[Vec<String>]) {
    let limit = terminal_width();
    let mut columns: Vec<usize> = (0..headers.len()).collect();
    let visible_rows = |columns: &[usize]| {
        let mut visible: Vec<Vec<String>> = rows
            .iter()
            .map(|r| r.iter().map(|s| clean(s)).collect())
            .collect();
        if !columns.iter().any(|i| headers[*i] == "ACCOUNT") {
            if let (Some(account), Some(session)) = (
                headers.iter().position(|h| *h == "ACCOUNT"),
                headers.iter().position(|h| *h == "SESSION"),
            ) {
                // Keep same-named sessions distinguishable after hiding ACCOUNT.
                for (i, row) in rows.iter().enumerate() {
                    if rows.iter().filter(|r| r[session] == row[session]).count() > 1 {
                        visible[i][session] = clean(&format!("{}/{}", row[account], row[session]));
                    }
                }
            }
        }
        visible
    };
    let desired = |column: usize, visible: &[Vec<String>]| {
        visible
            .iter()
            .map(|r| text_width(&r[column]))
            .max()
            .unwrap_or(0)
            .max(headers[column].len())
            .min(42)
    };
    let minimum = |column: usize, visible: &[Vec<String>]| {
        desired(column, visible).min(match headers[column] {
            "SESSION" => 12,
            "ACCOUNT" => 10,
            "WORKSPACE" => 14,
            "SYNC" => 12,
            _ => headers[column].len(),
        })
    };
    loop {
        let visible = visible_rows(&columns);
        let needed = columns.iter().map(|i| minimum(*i, &visible)).sum::<usize>()
            + 2 * columns.len().saturating_sub(1);
        if needed <= limit || columns.len() == 1 {
            break;
        }
        let drop = ["SYNC", "WORKSPACE", "ACCOUNT", "RUNTIME", "STATUS"]
            .iter()
            .find_map(|name| columns.iter().position(|i| headers[*i] == *name));
        if let Some(index) = drop {
            columns.remove(index);
        } else {
            break;
        }
    }
    let visible = visible_rows(&columns);
    let mut widths: Vec<usize> = columns.iter().map(|i| desired(*i, &visible)).collect();
    while widths.iter().sum::<usize>() + 2 * widths.len().saturating_sub(1) > limit {
        let next = widths
            .iter()
            .enumerate()
            .filter(|(i, w)| **w > minimum(columns[*i], &visible))
            .max_by_key(|(_, w)| **w)
            .map(|(i, _)| i)
            .or_else(|| {
                widths
                    .iter()
                    .enumerate()
                    .filter(|(_, w)| **w > 1)
                    .max_by_key(|(_, w)| **w)
                    .map(|(i, _)| i)
            });
        if let Some(i) = next {
            widths[i] -= 1;
        } else {
            break;
        }
    }
    let print_row = |row: &[String]| {
        let line = columns
            .iter()
            .enumerate()
            .map(|(j, i)| {
                let text = fit(&row[*i], widths[j]);
                format!(
                    "{text}{}",
                    " ".repeat(widths[j].saturating_sub(text_width(&text)))
                )
            })
            .collect::<Vec<_>>()
            .join("  ");
        println!("{}", line.trim_end());
    };
    print_row(&headers.iter().map(|s| s.to_string()).collect::<Vec<_>>());
    for row in &visible {
        print_row(row);
    }
}
pub fn sessions(
    filter: Option<&str>,
    name: Option<&str>,
    json_output: bool,
    details: bool,
) -> Result<()> {
    if !recover(filter)? {
        bail!("No saved Google account. Run Colab auth login.");
    }
    let data = registry()?;
    let mut all = Vec::new();
    let mut failed = false;
    for (email, _) in profiles(filter)? {
        if email.is_empty() {
            continue;
        }
        activate(&email, &data)?;
        match inventory(name) {
            Ok(rows) => {
                for mut row in rows {
                    row["account"] = json!(email);
                    all.push(row);
                }
            }
            Err(error) => {
                failed = true;
                eprintln!(
                    "{}: {error}; continuing with other accounts.",
                    display(&email)
                );
            }
        }
    }
    if json_output {
        println!("{}", serde_json::to_string_pretty(&all)?);
    } else {
        if all.is_empty() {
            println!(
                "No active sessions{}.",
                if name.is_some() {
                    " matching the selected name"
                } else {
                    ""
                }
            );
        } else {
            let has_sync = all.iter().any(|r| {
                r["local_folder"].is_string()
                    || r["sync_pairs"].as_array().is_some_and(|p| !p.is_empty())
            });
            let mut headers = vec!["ACCOUNT", "SESSION", "RUNTIME", "STATUS", "WORKSPACE"];
            if has_sync {
                headers.push("SYNC");
            }
            let rows = all
                .iter()
                .map(|r| {
                    let account = cell(r, "account");
                    let account = account
                        .strip_suffix("@gmail.com")
                        .unwrap_or(&account)
                        .to_owned();
                    let mut row = vec![
                        account,
                        cell(r, "session"),
                        cell(r, "runtime"),
                        cell(r, "status"),
                        cell(r, "workspace"),
                    ];
                    if has_sync {
                        let mut sync = Vec::new();
                        if r["local_folder"].is_string() {
                            sync.push(format!("{} -> Colab", short_path(&cell(r, "local_folder"))));
                        }
                        if let Some(pairs) = r["sync_pairs"].as_array() {
                            for pair in pairs {
                                sync.push(format!(
                                    "{} {} {}",
                                    short_path(&cell(pair, "left")),
                                    cell(pair, "direction"),
                                    short_path(&cell(pair, "right"))
                                ));
                            }
                        }
                        row.push(if sync.is_empty() {
                            "—".into()
                        } else {
                            sync.join("; ")
                        });
                    }
                    row
                })
                .collect::<Vec<_>>();
            table(&headers, &rows);
            if details {
                for r in &all {
                    println!(
                        "\n{}  ({})",
                        clean(&cell(r, "session")),
                        clean(display(&cell(r, "account")))
                    );
                    println!("  Endpoint   {}", clean(&cell(r, "endpoint")));
                    println!(
                        "  Runtime    {} / {} / {}",
                        clean(&cell(r, "runtime")),
                        clean(&cell(r, "shape")),
                        clean(&cell(r, "status"))
                    );
                    println!(
                        "  Drive      {} (read/write; current mount not checked)",
                        clean(&cell(r, "drive_folder"))
                    );
                    println!("  Workspace  {}", clean(&cell(r, "workspace")));
                    if r["local_folder"].is_string() {
                        println!(
                            "  Auto sync  {} -> {} (before operations)",
                            clean(&cell(r, "local_folder")),
                            clean(&cell(r, "workspace"))
                        );
                    }
                    if let Some(pairs) = r["sync_pairs"].as_array() {
                        for pair in pairs {
                            println!(
                                "  Sync       {} {} {}",
                                clean(&cell(pair, "left")),
                                clean(&cell(pair, "direction")),
                                clean(&cell(pair, "right"))
                            );
                        }
                    }
                }
            }
        }
    }
    if failed {
        bail!("Some accounts could not be queried; results are incomplete.");
    }
    Ok(())
}
pub fn delete_all(filter: Option<&str>) -> Result<()> {
    if !recover(filter)? {
        bail!("No saved Google account. Run Colab auth login.");
    }
    let data = registry()?;
    let mut failed = false;
    let mut deleted = 0;
    for (email, _) in profiles(filter)? {
        if email.is_empty() {
            continue;
        }
        activate(&email, &data)?;
        let result = (|| -> Result<()> {
            let rows = inventory(None)?;
            for row in &rows {
                if let Some(names) = row["names"].as_array() {
                    for name in names {
                        if let Some(name) = name.as_str() {
                            crate::transport::disconnect(name)?;
                        }
                    }
                }
            }
            let endpoints: Vec<_> = rows.iter().filter_map(|r| r["endpoint"].as_str()).collect();
            if endpoints.is_empty() {
                return Ok(());
            }
            let output = crate::script_command(include_str!("delete_sessions.py"))?
                .arg(serde_json::to_string(&endpoints)?)
                .output()?;
            std::io::stderr().write_all(&output.stderr)?;
            let results: Vec<Value> =
                serde_json::from_slice(&output.stdout).context("Invalid delete result")?;
            for row in results {
                if row["deleted"] == true {
                    deleted += 1;
                    println!("Deleted: {} / {}", display(&email), cell(&row, "endpoint"));
                }
            }
            if !output.status.success() {
                bail!("one or more runtime deletions failed");
            }
            Ok(())
        })();
        if let Err(error) = result {
            failed = true;
            eprintln!(
                "{}: {error}; continuing with other accounts.",
                display(&email)
            );
        }
    }
    println!("Deleted {deleted} runtime(s).");
    if failed {
        bail!("Some runtimes could not be deleted. Run Colab session list to inspect remaining runtimes.");
    }
    Ok(())
}
pub fn logout(filter: Option<&str>, all: bool) -> Result<()> {
    recover(filter)?;
    let data = registry()?;
    let selected = filter
        .map(str::to_lowercase)
        .or_else(|| default_email(&data).map(str::to_owned));
    let mut failed = false;
    let mut count = 0;
    for (email, profile) in profiles(if all { filter } else { selected.as_deref() })? {
        if email.is_empty() {
            continue;
        }
        activate(&email, &data)?;
        let result = (|| -> Result<()> {
            let path = profile.join("sessions.json");
            if path.exists() {
                let sessions: Value = serde_json::from_slice(&fs::read(path)?)?;
                if let Some(sessions) = sessions.as_object() {
                    for name in sessions.keys() {
                        crate::transport::disconnect(name)?;
                    }
                }
            }
            crate::transport::disconnect_account(&email)?;
            let mut process = crate::script_command(include_str!("account_admin.py"))?;
            process.args(["logout", &email]);
            if all && filter.is_none() {
                process.arg("clear-legacy");
            }
            let output = process.output()?;
            std::io::stdout().write_all(&output.stdout)?;
            std::io::stderr().write_all(&output.stderr)?;
            if !output.status.success() {
                bail!("Could not clear local credentials");
            }
            Ok(())
        })();
        if let Err(error) = result {
            failed = true;
            eprintln!("{}: {error}", display(&email));
        } else {
            count += 1;
        }
    }
    if count == 0 && !failed {
        println!("Already logged out.");
    }
    if failed {
        bail!("Some accounts could not be logged out.");
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
