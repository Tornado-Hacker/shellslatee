use std::env;
use std::fs;
use std::path::PathBuf;

// The engine wheel is embedded into the binary so a standalone portable .exe can
// install the engine with no sibling `resources/` folder. Resolving it here means
// the filename the binary looks for is always the file it actually carries — the
// two can no longer drift apart and produce a "missing engine wheel" install.
fn main() {
    let manifest = PathBuf::from(env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR"));
    let resources = manifest.join("resources");
    println!("cargo:rerun-if-changed=resources");

    let mut wheels: Vec<PathBuf> = Vec::new();
    if let Ok(entries) = fs::read_dir(&resources) {
        for entry in entries.flatten() {
            let path = entry.path();
            if !path.is_file() {
                continue;
            }
            let name = path.file_name().unwrap_or_default().to_string_lossy().to_string();
            if name.starts_with("shellslatee_engine-") && name.ends_with(".whl") {
                wheels.push(path);
            }
        }
    }

    if wheels.is_empty() {
        panic!(
            "no shellslatee_engine-*.whl in {} — build the wheel first (python -m build --wheel)",
            resources.display()
        );
    }
    if wheels.len() > 1 {
        let names: Vec<String> = wheels
            .iter()
            .map(|path| path.file_name().unwrap_or_default().to_string_lossy().to_string())
            .collect();
        panic!(
            "{} engine wheels in {} — keep exactly one: {:?}",
            wheels.len(),
            resources.display(),
            names
        );
    }

    let wheel = wheels.pop().expect("checked non-empty above");
    let name = wheel
        .file_name()
        .expect("wheel has a file name")
        .to_string_lossy()
        .into_owned();
    println!("cargo:rustc-env=SHELLSLATEE_WHEEL_PATH={}", wheel.display());
    println!("cargo:rustc-env=SHELLSLATEE_WHEEL_NAME={name}");

    tauri_build::build();
}
