#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

//! Shellslatee shell.
//!
//! Owns the Python engine (`shellslatee serve --port 0`) and exposes a tiny Rust
//! surface the UI can trust: config on disk, keys on disk, an HTTP proxy so the
//! webview never fights CORS, and process lifecycle.
//!
//! Discovery order for the engine:
//!   SHELLSLATEE_BIN   — path to an installed `shellslatee` executable
//!   SHELLSLATEE_REPO  — repo root; runs `$PYTHON -m shellslatee_engine` from there
//!   user scripts  — ~/.local/bin, %APPDATA%/Python/*/Scripts,
//!                   %LOCALAPPDATA%/Programs/Python/*/Scripts
//!   otherwise         — `shellslatee` on PATH

use std::collections::HashMap;
use std::fs;
use std::io::BufRead;
use std::io::BufReader;
use std::io::Write;
use std::net::SocketAddr;
use std::net::TcpStream;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc;
use std::sync::Mutex;
use std::time::Duration;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

use serde_json::{json, Value};
use tauri::{Emitter, Manager, State, WebviewUrl, WebviewWindowBuilder};

// A GUI process that spawns a console binary (python.exe, curl, pip, the engine)
// hands it a fresh console window unless told otherwise. CREATE_NO_WINDOW keeps
// every child headless so nothing flashes on the taskbar.
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

fn hide_console(command: &mut Command) -> &mut Command {
    #[cfg(windows)]
    {
        command.creation_flags(CREATE_NO_WINDOW);
    }
    command
}

struct Backend {
    child: Mutex<Option<Child>>,
    base: Mutex<Option<String>>,
    error: Mutex<Option<String>>,
    // One restart at a time, whether the supervisor or the UI asked for it.
    restarting: AtomicBool,
    client: reqwest::Client,
}

const BACKEND_EVENT: &str = "shellslatee://backend";

// ---- crash capture ---------------------------------------------------------
// A shipped GUI build has no console, so a panic would otherwise vanish. Log it,
// relaunch once, and only if the relaunched copy also dies show a native box.

fn crash_log_path() -> PathBuf {
    config_home().join("logs").join("crash.log")
}

fn write_crash_log(message: &str) -> Option<PathBuf> {
    let path = crash_log_path();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).ok()?;
    }
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|elapsed| elapsed.as_secs())
        .unwrap_or(0);
    let mut file = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)
        .ok()?;
    let _ = writeln!(file, "[{stamp}] {message}");
    Some(path)
}

#[cfg(windows)]
fn show_message(title: &str, body: &str) {
    #[link(name = "user32")]
    extern "system" {
        fn MessageBoxW(
            hwnd: *mut core::ffi::c_void,
            text: *const u16,
            caption: *const u16,
            utype: u32,
        ) -> i32;
    }
    let text: Vec<u16> = body.encode_utf16().chain(std::iter::once(0)).collect();
    let caption: Vec<u16> = title.encode_utf16().chain(std::iter::once(0)).collect();
    unsafe {
        // MB_OK | MB_ICONERROR | MB_TOPMOST
        MessageBoxW(core::ptr::null_mut(), text.as_ptr(), caption.as_ptr(), 0x0000_0010 | 0x0004_0000);
    }
}

#[cfg(not(windows))]
fn show_message(title: &str, body: &str) {
    eprintln!("{title}: {body}");
}

fn relaunch_once() {
    if std::env::var("SHELLSLATEE_RELAUNCHED").is_ok() {
        return;
    }
    if let Ok(exe) = std::env::current_exe() {
        let mut command = Command::new(exe);
        command.env("SHELLSLATEE_RELAUNCHED", "1");
        let _ = hide_console(&mut command).spawn();
    }
}

fn install_panic_hook() {
    std::panic::set_hook(Box::new(|info| {
        let message = format!("panic: {info}");
        let log = write_crash_log(&message);
        if std::env::var("SHELLSLATEE_RELAUNCHED").is_ok() {
            let body = match &log {
                Some(path) => format!(
                    "Shellslatee hit an unexpected problem.\n\nDetails were saved to:\n{}\n\nReopen Shellslatee to continue.",
                    path.display()
                ),
                None => "Shellslatee hit an unexpected problem.\n\nReopen Shellslatee to continue.".to_string(),
            };
            show_message("Shellslatee", &body);
        } else {
            relaunch_once();
        }
    }));
}

// Used where the app cannot continue at all (window or client could not start).
fn fatal(message: &str) -> ! {
    let path = write_crash_log(message);
    let body = match path {
        Some(path) => format!("{message}\n\nDetails were saved to:\n{}\n\nReopen Shellslatee to continue.", path.display()),
        None => format!("{message}\n\nReopen Shellslatee to continue."),
    };
    show_message("Shellslatee", &body);
    std::process::exit(1)
}

fn config_home() -> PathBuf {
    dirs::home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".config")
        .join("shellslatee")
}

fn config_path() -> PathBuf {
    config_home().join("desktop.json")
}

fn keys_path() -> PathBuf {
    config_home().join("desktop_keys.json")
}

fn env_name(provider: &str) -> Option<&'static str> {
    match provider {
        "aikey" => Some("AIKEY_API_KEY"),
        "openrouter" => Some("OPENROUTER_API_KEY"),
        "openai" => Some("OPENAI_API_KEY"),
        _ => None,
    }
}

fn provider_base(provider: &str) -> Option<String> {
    match provider {
        // The live service still answers on this host; AIKEY_BASE_URL overrides
        // it for anyone pointing at a different deployment.
        "aikey" => Some(
            std::env::var("AIKEY_BASE_URL").unwrap_or_else(|_| "https://tokenharbor.ai/v1".to_string()),
        ),
        "openrouter" => Some("https://openrouter.ai/api/v1".to_string()),
        "openai" => Some("https://api.openai.com/v1".to_string()),
        _ => None,
    }
}

fn provider_default_model(provider: &str) -> &'static str {
    match provider {
        "aikey" => "deepseek-v4.1-flash:free",
        "openrouter" => "meta-llama/llama-3.3-70b-instruct:free",
        "openai" => "gpt-4o-mini",
        _ => "mock",
    }
}

fn read_keys() -> HashMap<String, String> {
    fs::read_to_string(keys_path())
        .ok()
        .and_then(|raw| serde_json::from_str(&raw).ok())
        .unwrap_or_default()
}

#[cfg(unix)]
fn lock_down(path: &Path) {
    use std::os::unix::fs::PermissionsExt;
    if let Ok(metadata) = fs::metadata(path) {
        let mut permissions = metadata.permissions();
        permissions.set_mode(0o600);
        let _ = fs::set_permissions(path, permissions);
    }
}

#[cfg(not(unix))]
fn lock_down(_path: &Path) {}

fn write_atomic(path: &Path, contents: &str) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| format!("could not create {}: {error}", parent.display()))?;
    }
    let tmp = path.with_extension("tmp");
    fs::write(&tmp, contents).map_err(|error| format!("could not write {}: {error}", tmp.display()))?;
    // Windows refuses to rename over an existing file, so fall back to a direct
    // write there. Unix gets the atomic rename.
    if fs::rename(&tmp, path).is_err() {
        fs::write(path, contents).map_err(|error| format!("could not replace {}: {error}", path.display()))?;
        let _ = fs::remove_file(&tmp);
    }
    lock_down(path);
    Ok(())
}

// Best effort: a stale keychain entry outranks the environment in the engine's
// resolver (file -> keychain -> env), so app-managed keys must clear it.
fn clear_keychain(provider: &str) {
    #[cfg(target_os = "macos")]
    {
        let _ = Command::new("security")
            .args(["delete-generic-password", "-a", provider, "-s", "shellslatee"])
            .output();
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        let _ = Command::new("secret-tool")
            .args(["clear", "service", "shellslatee", "account", provider])
            .output();
    }
    #[cfg(windows)]
    {
        let _ = provider;
    }
}

fn write_keys(keys: &HashMap<String, String>) -> Result<(), String> {
    let raw = serde_json::to_string_pretty(keys).map_err(|error| format!("could not encode keys: {error}"))?;
    write_atomic(&keys_path(), &raw)
}

// `pip install --user` drops the console script outside PATH for most Windows
// installs, and GUI processes rarely inherit a shell PATH at all, so the usual
// interpreter-script roots are probed before falling back to a bare lookup.
fn engine_from_user_scripts() -> Option<PathBuf> {
    let exe = if cfg!(windows) { "shellslatee.exe" } else { "shellslatee" };
    let mut roots: Vec<PathBuf> = Vec::new();

    if let Some(home) = dirs::home_dir() {
        roots.push(home.join(".local").join("bin"));
    }
    if let Some(roaming) = dirs::config_dir() {
        roots.push(roaming.join("Python"));
    }
    if let Some(local) = dirs::data_local_dir() {
        roots.push(local.join("Programs").join("Python"));
    }

    for root in roots {
        if root.ends_with("bin") {
            let candidate = root.join(exe);
            if candidate.is_file() {
                return Some(candidate);
            }
            continue;
        }
        let Ok(entries) = fs::read_dir(&root) else { continue };
        for entry in entries.flatten() {
            let candidate = entry.path().join("Scripts").join(exe);
            if candidate.is_file() {
                return Some(candidate);
            }
        }
    }
    None
}


// ---- one-click setup -------------------------------------------------------
// The engine wheel is embedded in the binary by build.rs, so both the installed
// app and the bare portable .exe can install the engine with only Python on the
// machine. The name and path come from whatever wheel build.rs found, so the
// binary can never look for a differently-named file than the one it carries.
const ENGINE_WHEEL_NAME: &str = env!("SHELLSLATEE_WHEEL_NAME");
static ENGINE_WHEEL_BYTES: &[u8] = include_bytes!(env!("SHELLSLATEE_WHEEL_PATH"));
const ENGINE_WHEEL_PREFIX: &str = "shellslatee_engine-";
const ENGINE_WHEEL_SUFFIX: &str = "-py3-none-any.whl";
const PYTHON_URL: &str = "https://www.python.org/ftp/python/3.12.6/python-3.12.6-amd64.exe";

fn python_candidates() -> Vec<Vec<String>> {
    if cfg!(windows) {
        vec![
            vec!["python".to_string()],
            vec!["py".to_string(), "-3".to_string()],
            vec!["python3".to_string()],
        ]
    } else {
        vec![vec!["python3".to_string()], vec!["python".to_string()]]
    }
}

fn python_version(command: &[String]) -> Option<String> {
    let mut process = Command::new(&command[0]);
    for arg in &command[1..] {
        process.arg(arg);
    }
    let output = hide_console(&mut process).arg("--version").output().ok()?;
    if !output.status.success() {
        return None;
    }
    let text = if output.stdout.is_empty() {
        String::from_utf8_lossy(&output.stderr).trim().to_string()
    } else {
        String::from_utf8_lossy(&output.stdout).trim().to_string()
    };
    text.strip_prefix("Python ").map(|value| value.trim().to_string())
}

fn probe_python() -> Option<(Vec<String>, String)> {
    for candidate in python_candidates() {
        if let Some(version) = python_version(&candidate) {
            let parts: Vec<u32> = version.split('.').take(2).filter_map(|part| part.parse().ok()).collect();
            if parts.len() == 2 && (parts[0] > 3 || (parts[0] == 3 && parts[1] >= 10)) {
                return Some((candidate, version));
            }
        }
    }
    None
}

fn engine_on_path() -> bool {
    let mut command = Command::new("shellslatee");
    command
        .arg("--version")
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    hide_console(&mut command)
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
}

fn wheels_in(dir: &Path) -> Vec<PathBuf> {
    let mut wheels: Vec<PathBuf> = Vec::new();
    let Ok(entries) = fs::read_dir(dir) else { return wheels };
    for entry in entries.flatten() {
        let path = entry.path();
        if !path.is_file() {
            continue;
        }
        let Some(name) = path.file_name().and_then(|name| name.to_str()) else {
            continue;
        };
        if name.starts_with(ENGINE_WHEEL_PREFIX) && name.ends_with(ENGINE_WHEEL_SUFFIX) {
            wheels.push(path);
        }
    }
    // Newest staged wheel first when a dev tree keeps more than one.
    wheels.sort();
    wheels.reverse();
    wheels
}

/// Directories that may hold an engine wheel, most specific first: the installed
/// resource folder, then the folder beside the executable, then the dev tree.
fn wheel_dirs(app: &tauri::AppHandle) -> Vec<PathBuf> {
    let mut dirs: Vec<PathBuf> = Vec::new();
    if let Ok(dir) = app.path().resource_dir() {
        dirs.push(dir.join("resources"));
        dirs.push(dir);
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            dirs.push(parent.join("resources"));
            dirs.push(parent.to_path_buf());
        }
    }
    if let Ok(cwd) = std::env::current_dir() {
        dirs.push(cwd.join("src-tauri").join("resources"));
        dirs.push(cwd.join("resources"));
        dirs.push(cwd.join("dist-engine"));
    }
    dirs
}

fn wheel_candidates(app: &tauri::AppHandle) -> Vec<PathBuf> {
    wheel_dirs(app).iter().flat_map(|dir| wheels_in(dir)).collect()
}

/// Spool the embedded wheel to disk when no on-disk copy is next to the app.
/// This is what makes the standalone portable `.exe` self-sufficient.
fn stage_embedded_wheel() -> Result<PathBuf, String> {
    let dir = std::env::temp_dir().join("shellslatee-setup");
    fs::create_dir_all(&dir).map_err(|error| format!("could not create {}: {error}", dir.display()))?;
    let path = dir.join(ENGINE_WHEEL_NAME);
    let current = fs::read(&path).ok();
    if current.as_deref() != Some(ENGINE_WHEEL_BYTES) {
        fs::write(&path, ENGINE_WHEEL_BYTES)
            .map_err(|error| format!("could not write {}: {error}", path.display()))?;
    }
    Ok(path)
}

fn download_file(url: &str, destination: &Path) -> Result<(), String> {
    let target = destination.to_string_lossy().to_string();
    // curl ships with Windows 10+; PowerShell is the fallback.
    let mut curl = Command::new("curl");
    curl.args(["-L", "--fail", "--silent", "--show-error", "-o", &target, url]);
    let curl = hide_console(&mut curl).status();
    if let Ok(status) = curl {
        if status.success() {
            return Ok(());
        }
    }
    let script = format!(
        "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri '{url}' -OutFile '{}'",
        target.replace('\'', "''")
    );
    let mut powershell = Command::new("powershell");
    powershell.args(["-NoProfile", "-NonInteractive", "-Command", &script]);
    let status = hide_console(&mut powershell)
        .status()
        .map_err(|error| format!("could not start a downloader: {error}"))?;
    if status.success() {
        Ok(())
    } else {
        Err("the Python download failed — check your connection and try again".to_string())
    }
}

#[tauri::command]
fn check_prereqs(app: tauri::AppHandle) -> Value {
    let python = probe_python();
    let engine = engine_from_user_scripts().is_some() || engine_on_path();
    let ready = python.is_some() && engine;
    // The wheel is embedded in the binary, so every build can install the
    // engine; report an on-disk copy when one is also staged.
    let wheel_path = wheel_candidates(&app)
        .into_iter()
        .next()
        .map(|path| path.display().to_string());
    json!({
        "python": python.as_ref().map(|(_, version)| version.clone()),
        "python_hint": python.as_ref().map(|(command, _)| command.join(" ")),
        "engine": engine,
        "wheel": true,
        "wheel_path": wheel_path,
        "ready": ready,
    })
}

#[tauri::command]
fn install_prereqs(app: tauri::AppHandle) -> Result<Value, String> {
    let mut steps: Vec<String> = Vec::new();

    let (python, version) = match probe_python() {
        Some(found) => found,
        None => {
            if !cfg!(windows) {
                return Err("Install Python 3.10+ with your package manager, then retry.".to_string());
            }
            let dir = std::env::temp_dir().join("shellslatee-setup");
            fs::create_dir_all(&dir).map_err(|error| format!("could not create {}: {error}", dir.display()))?;
            let installer = dir.join("python-3.12.6-amd64.exe");
            if !installer.is_file() {
                download_file(PYTHON_URL, &installer)?;
            }
            steps.push("Python 3.12.6 downloaded".to_string());
            let mut setup = Command::new(&installer);
            setup.args(["/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_test=0", "Include_launcher=1"]);
            let status = hide_console(&mut setup)
                .status()
                .map_err(|error| format!("could not start the Python installer: {error}"))?;
            if !status.success() {
                return Err(format!("the Python installer exited with {status}"));
            }
            steps.push("Python 3.12.6 installed".to_string());
            probe_python().ok_or_else(|| {
                "Python installed but not visible yet — restart Windows, then open Shellslatee again".to_string()
            })?
        }
    };

    let wheel = match wheel_candidates(&app).into_iter().next() {
        Some(path) => path,
        None => stage_embedded_wheel()?,
    };

    let mut command = Command::new(&python[0]);
    for arg in &python[1..] {
        command.arg(arg);
    }
    let output = hide_console(&mut command)
        .args(["-m", "pip", "install", "--user", "--upgrade"])
        .arg(&wheel)
        .output()
        .map_err(|error| format!("could not run pip: {error}"))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        let tail: Vec<&str> = stderr.lines().rev().take(4).collect();
        let tail: Vec<&str> = tail.into_iter().rev().collect();
        return Err(format!("pip failed: {}", tail.join(" | ")));
    }
    steps.push("local engine installed".to_string());

    Ok(json!({ "ok": true, "python": version, "steps": steps }))
}

fn spawn_backend(keys: &HashMap<String, String>) -> Result<(Child, String), String> {
    let mut command = if let Ok(bin) = std::env::var("SHELLSLATEE_BIN") {
        Command::new(bin)
    } else if let Ok(repo) = std::env::var("SHELLSLATEE_REPO") {
        let default_python = if cfg!(windows) { "python" } else { "python3" };
        let python = std::env::var("PYTHON").unwrap_or_else(|_| default_python.to_string());
        let mut command = Command::new(python);
        command.arg("-m").arg("shellslatee_engine").current_dir(repo);
        command
    } else if let Some(bin) = engine_from_user_scripts() {
        Command::new(bin)
    } else {
        Command::new("shellslatee")
    };

    for (provider, key) in keys {
        if let Some(name) = env_name(provider) {
            command.env(name, key);
        }
    }
    // Windows pipes default to the ANSI code page; force UTF-8 so the startup
    // banner we parse survives intact.
    command.env("PYTHONIOENCODING", "utf-8").env("PYTHONUTF8", "1");

    let mut child = hide_console(&mut command)
        .arg("serve")
        .arg("--port")
        .arg("0")
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .stdin(Stdio::null())
        .spawn()
        .map_err(|error| {
            format!(
                "could not start the local engine: {error}. Install it with `pip install shellslatee-engine`, \
                 add it to PATH, or set SHELLSLATEE_BIN / SHELLSLATEE_REPO."
            )
        })?;

    let stderr = match child.stderr.take() {
        Some(stderr) => stderr,
        None => {
            let _ = child.kill();
            return Err("the engine produced no stderr to read".to_string());
        }
    };

    let (tx, rx) = mpsc::channel::<String>();
    let tail: std::sync::Arc<Mutex<Vec<String>>> = std::sync::Arc::new(Mutex::new(Vec::new()));
    let tail_writer = tail.clone();
    std::thread::spawn(move || {
        let mut reader = BufReader::new(stderr);
        let mut buffer: Vec<u8> = Vec::new();
        loop {
            buffer.clear();
            match reader.read_until(b'\n', &mut buffer) {
                Ok(0) | Err(_) => break,
                Ok(_) => {
                    // Decode lossily: a stray non-UTF-8 byte must never stall the
                    // reader, because the URL line arrives after the banner.
                    let line = String::from_utf8_lossy(&buffer).trim().to_string();
                    if line.is_empty() {
                        continue;
                    }
                    if let Ok(mut log) = tail_writer.lock() {
                        log.push(line.clone());
                        if log.len() > 6 {
                            log.remove(0);
                        }
                    }
                    if let Some(rest) = line.split("shellslatee serve: http://").nth(1) {
                        let _ = tx.send(format!("http://{}", rest.trim()));
                    }
                }
            }
        }
    });

    let url = match rx.recv_timeout(Duration::from_secs(30)) {
        Ok(url) => url,
        Err(_) => {
            let _ = child.kill();
            let _ = child.wait();
            let detail = tail
                .lock()
                .map(|log| log.join(" | "))
                .unwrap_or_default();
            return Err(if detail.is_empty() {
                "the engine did not report a loopback URL in time".to_string()
            } else {
                format!("the engine did not report a loopback URL in time ({detail})")
            });
        }
    };

    if let Err(error) = wait_for_port(&url) {
        let _ = child.kill();
        let _ = child.wait();
        return Err(error);
    }

    Ok((child, url))
}

fn wait_for_port(url: &str) -> Result<(), String> {
    let authority = url
        .strip_prefix("http://")
        .ok_or_else(|| format!("unsupported engine URL: {url}"))?;
    let address = authority
        .parse()
        .map_err(|error| format!("bad engine address {authority}: {error}"))?;
    for _ in 0..150 {
        if TcpStream::connect_timeout(&address, Duration::from_millis(200)).is_ok() {
            return Ok(());
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    Err(format!("the engine never accepted connections at {authority}"))
}

fn kill_child(state: &Backend) {
    if let Ok(mut guard) = state.child.lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

fn status_snapshot(state: &Backend) -> Value {
    let base = state.base.lock().ok().and_then(|guard| guard.clone());
    let error = state.error.lock().ok().and_then(|guard| guard.clone());
    json!({ "ready": base.is_some(), "base": base, "error": error, "version": null })
}

// Kill whatever was running, start a fresh engine, record the new loopback URL.
// The caller decides whether to surface the result; the supervisor and the
// `restart_backend` command both land here so the policy lives in one place.
fn restart_engine(state: &Backend) -> Result<String, String> {
    kill_child(state);
    let keys = read_keys();
    match spawn_backend(&keys) {
        Ok((child, url)) => {
            if let Ok(mut guard) = state.child.lock() {
                *guard = Some(child);
            }
            if let Ok(mut guard) = state.base.lock() {
                *guard = Some(url.clone());
            }
            if let Ok(mut guard) = state.error.lock() {
                *guard = None;
            }
            Ok(url)
        }
        Err(error) => {
            if let Ok(mut guard) = state.base.lock() {
                *guard = None;
            }
            if let Ok(mut guard) = state.error.lock() {
                *guard = Some(error.clone());
            }
            Err(error)
        }
    }
}

fn engine_port_alive(base: &str) -> bool {
    let authority = match base.strip_prefix("http://") {
        Some(authority) => authority,
        None => return false,
    };
    let address: SocketAddr = match authority.parse() {
        Ok(address) => address,
        Err(_) => return false,
    };
    TcpStream::connect_timeout(&address, Duration::from_millis(300)).is_ok()
}

// Watches the engine and brings it back on its own when it dies (engine panic,
// OOM, an over-eager antivirus kill). Only supervises an engine that came up at
// least once, so a machine without the engine installed is left to the setup UI.
fn start_supervisor(app: tauri::AppHandle) {
    std::thread::spawn(move || {
        let mut streak: u32 = 0;
        loop {
            std::thread::sleep(Duration::from_secs(2));
            let state = app.state::<Backend>();
            let backend = state.inner();
            let base = match backend.base.lock().ok().and_then(|guard| guard.clone()) {
                Some(base) => base,
                None => continue,
            };
            if engine_port_alive(&base) {
                streak = 0;
                continue;
            }
            // A single dropped connection is not a crash; confirm before acting.
            std::thread::sleep(Duration::from_millis(700));
            if engine_port_alive(&base) {
                continue;
            }
            if backend.restarting.swap(true, Ordering::SeqCst) {
                continue;
            }
            let result = restart_engine(backend);
            backend.restarting.store(false, Ordering::SeqCst);
            if result.is_err() {
                streak = (streak + 1).min(5);
            }
            let _ = app.emit(BACKEND_EVENT, status_snapshot(backend));
            if result.is_err() {
                let backoff = Duration::from_millis(500u64 * (1u64 << streak));
                std::thread::sleep(backoff.min(Duration::from_secs(20)));
            }
        }
    });
}

#[tauri::command]
fn load_config() -> Result<Value, String> {
    let raw = fs::read_to_string(config_path()).ok();
    match raw {
        Some(raw) => serde_json::from_str(&raw).map_err(|error| format!("config is not valid JSON: {error}")),
        None => Ok(Value::Null),
    }
}

#[tauri::command]
fn save_config(config: Value) -> Result<(), String> {
    let raw = serde_json::to_string_pretty(&config).map_err(|error| format!("could not encode config: {error}"))?;
    write_atomic(&config_path(), &raw)
}

#[tauri::command]
fn save_api_key(provider: String, key: String) -> Result<(), String> {
    let trimmed = key.trim();
    if trimmed.is_empty() {
        return Err("the key is empty".to_string());
    }
    let mut keys = read_keys();
    keys.insert(provider.clone(), trimmed.to_string());
    write_keys(&keys)?;
    clear_keychain(&provider);
    if provider == "aikey" {
        write_atomic(&config_home().join("aikey_key"), trimmed)?;
    }
    Ok(())
}

#[tauri::command]
fn clear_api_key(provider: String) -> Result<(), String> {
    let mut keys = read_keys();
    keys.remove(&provider);
    write_keys(&keys)?;
    clear_keychain(&provider);
    if provider == "aikey" {
        let _ = fs::remove_file(config_home().join("aikey_key"));
    }
    Ok(())
}

#[tauri::command]
async fn verify_api_key(provider: String, key: String) -> Result<Value, String> {
    let trimmed = key.trim();
    if trimmed.is_empty() {
        return Ok(json!({ "ok": false, "detail": "Paste a key first." }));
    }
    let base = match provider_base(&provider) {
        Some(base) => base,
        None => return Ok(json!({ "ok": false, "detail": "This provider is local or has no key to check." })),
    };
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(25))
        .build()
        .map_err(|error| format!("could not build the HTTP client: {error}"))?;
    let payload = json!({
        "model": provider_default_model(&provider),
        "messages": [{ "role": "user", "content": "Reply with the single word: ok" }],
        "max_tokens": 1,
        "temperature": 0
    });
    let response = client
        .post(format!("{base}/chat/completions"))
        .bearer_auth(trimmed)
        .json(&payload)
        .send()
        .await;
    match response {
        Ok(response) => {
            let status = response.status();
            if status.is_success() {
                Ok(json!({ "ok": true, "detail": format!("{} accepted the key — test completion ran.", provider) }))
            } else {
                let body = response.text().await.unwrap_or_default();
                let body: String = body.chars().take(220).collect();
                Ok(json!({
                    "ok": false,
                    "detail": format!("{} returned {} — {}", provider, status.as_u16(), body.trim())
                }))
            }
        }
        Err(error) => Ok(json!({
            "ok": false,
            "detail": format!("could not reach {provider}: {error}")
        })),
    }
}

#[tauri::command]
async fn api_request(
    state: State<'_, Backend>,
    method: String,
    path: String,
    body: Option<String>,
) -> Result<String, String> {
    if !path.starts_with("/api/") {
        return Err("400 only /api/ paths are proxied".to_string());
    }
    let base = state
        .base
        .lock()
        .ok()
        .and_then(|guard| guard.clone())
        .ok_or_else(|| "503 the local engine is not running".to_string())?;
    let url = format!("{base}{path}");
    let client = state.client.clone();
    let verb = method.to_uppercase();
    let mut request = match verb.as_str() {
        "GET" => client.get(&url),
        "POST" => client.post(&url),
        "PUT" => client.put(&url),
        "PATCH" => client.patch(&url),
        "DELETE" => client.delete(&url),
        _ => return Err(format!("400 unsupported method {method}")),
    };
    if let Some(body) = body {
        request = request
            .header(reqwest::header::CONTENT_TYPE, "application/json")
            .body(body);
    }
    let response = request
        .send()
        .await
        .map_err(|error| format!("502 engine request failed: {error}"))?;
    let status = response.status();
    let text = response.text().await.unwrap_or_default();
    if !status.is_success() {
        return Err(format!("{} {}", status.as_u16(), text));
    }
    Ok(text)
}

#[tauri::command]
async fn backend_status(state: State<'_, Backend>) -> Result<Value, String> {
    let base = state.base.lock().ok().and_then(|guard| guard.clone());
    let error = state.error.lock().ok().and_then(|guard| guard.clone());
    let Some(base) = base else {
        return Ok(json!({ "ready": false, "base": null, "error": error, "version": null }));
    };
    let client = state.client.clone();
    match client
        .get(format!("{base}/api/health"))
        .timeout(Duration::from_secs(4))
        .send()
        .await
    {
        Ok(response) if response.status().is_success() => {
            let body: Value = response.json().await.unwrap_or(Value::Null);
            let version = body.get("version").and_then(Value::as_str).map(str::to_string);
            Ok(json!({ "ready": true, "base": base, "error": null, "version": version }))
        }
        Ok(response) => Ok(json!({
            "ready": false,
            "base": base,
            "error": format!("engine health check returned {}", response.status().as_u16()),
            "version": null
        })),
        Err(error) => Ok(json!({
            "ready": false,
            "base": base,
            "error": format!("engine is unreachable: {error}"),
            "version": null
        })),
    }
}

#[tauri::command]
fn restart_backend(state: State<'_, Backend>) -> Result<Value, String> {
    if state.restarting.swap(true, Ordering::SeqCst) {
        return Ok(status_snapshot(&state));
    }
    let result = restart_engine(&state);
    state.restarting.store(false, Ordering::SeqCst);
    match result {
        Ok(url) => Ok(json!({ "ready": true, "base": url, "error": null, "version": null })),
        Err(error) => Ok(json!({ "ready": false, "base": null, "error": error, "version": null })),
    }
}

#[tauri::command]
fn open_path(path: String) -> Result<(), String> {
    if !Path::new(&path).exists() {
        return Err(format!("{path} does not exist"));
    }
    #[cfg(target_os = "windows")]
    let result = Command::new("explorer").arg(&path).spawn();
    #[cfg(target_os = "macos")]
    let result = Command::new("open").arg(&path).spawn();
    #[cfg(all(unix, not(target_os = "macos")))]
    let result = Command::new("xdg-open").arg(&path).spawn();
    result.map(|_| ()).map_err(|error| format!("could not open {path}: {error}"))
}

// The installer writes the notes folder it created to this file so the app and
// the setup screen agree on one location instead of guessing.
fn notes_marker_path() -> PathBuf {
    config_home().join("notes_dir.txt")
}

fn dir_is_writable(path: &Path) -> bool {
    if fs::create_dir_all(path).is_err() {
        return false;
    }
    let probe = path.join(".shellslatee-write-test");
    match fs::write(&probe, b"ok") {
        Ok(()) => {
            let _ = fs::remove_file(&probe);
            true
        }
        Err(_) => false,
    }
}

#[tauri::command]
fn default_vault() -> Result<String, String> {
    let home = dirs::home_dir().ok_or_else(|| "could not find the home directory".to_string())?;
    let mut candidates: Vec<PathBuf> = Vec::new();
    // The installer's choice wins when that folder is still writable.
    if let Ok(marked) = fs::read_to_string(notes_marker_path()) {
        let marked = marked.trim();
        if !marked.is_empty() {
            candidates.push(PathBuf::from(marked));
        }
    }
    candidates.push(home.join("Shellslatee Notes"));
    if let Some(local) = dirs::data_local_dir() {
        candidates.push(local.join("Shellslatee").join("Notes"));
    }
    for candidate in candidates {
        if dir_is_writable(&candidate) {
            let _ = write_atomic(&notes_marker_path(), &candidate.to_string_lossy());
            return Ok(candidate.to_string_lossy().to_string());
        }
    }
    Err("no writable folder for notes; allow Shellslatee in antivirus folder protection or pick another folder".to_string())
}

fn main() {
    install_panic_hook();

    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(600))
        .build()
        .unwrap_or_else(|error| fatal(&format!("could not build the HTTP client: {error}")));

    let state = Backend {
        child: Mutex::new(None),
        base: Mutex::new(None),
        error: Mutex::new(None),
        restarting: AtomicBool::new(false),
        client,
    };

    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(state)
        .invoke_handler(tauri::generate_handler![
            load_config,
            save_config,
            backend_status,
            restart_backend,
            api_request,
            save_api_key,
            clear_api_key,
            verify_api_key,
            open_path,
            default_vault,
            check_prereqs,
            install_prereqs
        ])
        .setup(|app| {
            // Materialize the notes folder at startup; a locked-down Documents
            // folder makes default_vault fall back to the user profile.
            let _ = default_vault();
            {
                let state = app.state::<Backend>();
                let keys = read_keys();
                match spawn_backend(&keys) {
                    Ok((child, url)) => {
                        if let Ok(mut guard) = state.child.lock() {
                            *guard = Some(child);
                        }
                        if let Ok(mut guard) = state.base.lock() {
                            *guard = Some(url);
                        }
                    }
                    Err(error) => {
                        if let Ok(mut guard) = state.error.lock() {
                            *guard = Some(error);
                        }
                    }
                }
            }

            // Keep the engine alive on its own: a crash restarts it and the UI
            // is told over the event bus instead of asking the user to retry.
            start_supervisor(app.handle().clone());

            // Fit the window to the monitor: a hard 1320 logical px overflows
            // 1366x768 screens at 125% scaling (1229x614 logical).
            let (mut width, mut height) = (1320.0_f64, 880.0_f64);
            if let Ok(Some(monitor)) = app.primary_monitor() {
                let scale = monitor.scale_factor();
                let usable = monitor.size().to_logical::<f64>(scale);
                width = width.min((usable.width * 0.94).max(900.0));
                height = height.min((usable.height * 0.90).max(600.0));
            }

            if let Err(error) = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("Shellslatee")
                .inner_size(width, height)
                .min_inner_size(880.0, 560.0)
                .center()
                .build()
            {
                fatal(&format!("could not create the Shellslatee window: {error}"));
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .unwrap_or_else(|error| fatal(&format!("failed to start Shellslatee: {error}")))
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                if let Some(state) = app.try_state::<Backend>() {
                    kill_child(&state);
                }
            }
        });
}
