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
use std::io::{BufRead, BufReader};
use std::net::TcpStream;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::mpsc;
use std::sync::Mutex;
use std::time::Duration;

use serde_json::{json, Value};
use tauri::{Manager, State, WebviewUrl, WebviewWindowBuilder};

struct Backend {
    child: Mutex<Option<Child>>,
    base: Mutex<Option<String>>,
    error: Mutex<Option<String>>,
    client: reqwest::Client,
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

    let mut child = command
        .arg("serve")
        .arg("--port")
        .arg("0")
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
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
    std::thread::spawn(move || {
        let reader = BufReader::new(stderr);
        for line in reader.lines().map_while(Result::ok) {
            if let Some(rest) = line.split("shellslatee serve: http://").nth(1) {
                let _ = tx.send(format!("http://{}", rest.trim()));
            }
        }
    });

    let url = match rx.recv_timeout(Duration::from_secs(25)) {
        Ok(url) => url,
        Err(_) => {
            let _ = child.kill();
            let _ = child.wait();
            return Err("the engine did not report a loopback URL in time".to_string());
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
    kill_child(&state);
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
            Ok(json!({ "ready": true, "base": url, "error": null, "version": null }))
        }
        Err(error) => {
            if let Ok(mut guard) = state.base.lock() {
                *guard = None;
            }
            if let Ok(mut guard) = state.error.lock() {
                *guard = Some(error.clone());
            }
            Ok(json!({ "ready": false, "base": null, "error": error, "version": null }))
        }
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

#[tauri::command]
fn default_vault() -> Result<String, String> {
    let home = dirs::home_dir().ok_or_else(|| "could not find the home directory".to_string())?;
    let vault = dirs::document_dir().unwrap_or(home).join("Shellslatee Vault");
    fs::create_dir_all(&vault).map_err(|error| format!("could not create {}: {error}", vault.display()))?;
    Ok(vault.to_string_lossy().to_string())
}

fn main() {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(600))
        .build()
        .expect("could not build the HTTP client");

    let state = Backend {
        child: Mutex::new(None),
        base: Mutex::new(None),
        error: Mutex::new(None),
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
            default_vault
        ])
        .setup(|app| {
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

            WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("Shellslatee")
                .inner_size(1320.0, 880.0)
                .min_inner_size(960.0, 640.0)
                .build()?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build the Shellslatee window")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                if let Some(state) = app.try_state::<Backend>() {
                    kill_child(&state);
                }
            }
        });
}
