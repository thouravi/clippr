use serde_json::{json, Value};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use tauri::{AppHandle, Emitter};
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::Command;

fn project_root() -> PathBuf {
    // A GitHub Actions build bakes the runner path into CARGO_MANIFEST_DIR.
    // Walk up from the exe and use the checkout that holds the Python package
    // and the local venv, so a downloaded clippr.exe still runs on this PC.
    if let Ok(exe) = std::env::current_exe() {
        let mut current = exe.as_path();
        for _ in 0..8 {
            let Some(parent) = current.parent() else {
                break;
            };
            current = parent;
            let python_pkg = current.join("python").join("clippr");
            let venv = current.join(".venv").join("Scripts").join("python.exe");
            if python_pkg.is_dir() && venv.is_file() {
                return current.to_path_buf();
            }
        }
    }
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("src-tauri lives inside the repo")
        .to_path_buf()
}

fn clippr_home() -> PathBuf {
    if let Ok(override_home) = std::env::var("CLIPPR_HOME") {
        return PathBuf::from(override_home);
    }
    let profile = std::env::var("USERPROFILE").unwrap_or_else(|_| ".".into());
    PathBuf::from(profile).join(".clippr")
}

fn python_executable(root: &Path) -> PathBuf {
    if let Ok(explicit) = std::env::var("CLIPPR_PYTHON") {
        return PathBuf::from(explicit);
    }
    let venv = root.join(".venv").join("Scripts").join("python.exe");
    if venv.is_file() {
        return venv;
    }
    PathBuf::from("python")
}

fn clear_cancel() {
    let _ = fs::remove_file(clippr_home().join("cancel"));
}

#[cfg(windows)]
fn hide_console(command: &mut std::process::Command) {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x08000000;
    command.creation_flags(CREATE_NO_WINDOW);
}

async fn run_python(app: &AppHandle, args: Vec<String>) -> Result<Value, String> {
    let root = project_root();
    let python = python_executable(&root);
    let mut command = Command::new(&python);
    command
        .arg("-m")
        .arg("clippr")
        .args(&args)
        .current_dir(root.join("python"))
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    #[cfg(windows)]
    command.creation_flags(0x08000000);

    let mut child = command.spawn().map_err(|error| {
        format!(
            "Could not start Python at {}. Install the repo venv with python -m venv .venv and pip install -r python/requirements.txt. ({error})",
            python.display()
        )
    })?;

    let stderr = child.stderr.take().ok_or("Python stderr was unavailable")?;
    let app_for_logs = app.clone();
    let stderr_task = tokio::spawn(async move {
        let mut lines = BufReader::new(stderr).lines();
        let mut collected = String::new();
        while let Ok(Some(line)) = lines.next_line().await {
            if line.trim().is_empty() {
                continue;
            }
            collected.push_str(&line);
            collected.push('\n');
            let _ = app_for_logs.emit("clippr-progress", json!({"type": "log", "message": line}));
        }
        collected
    });

    let stdout = child.stdout.take().ok_or("Python stdout was unavailable")?;
    let mut lines = BufReader::new(stdout).lines();
    let mut outcome: Option<Value> = None;
    while let Ok(Some(line)) = lines.next_line().await {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        match serde_json::from_str::<Value>(trimmed) {
            Ok(payload) => match payload.get("type").and_then(|kind| kind.as_str()) {
                Some("result") => outcome = Some(payload),
                _ => {
                    let _ = app.emit("clippr-progress", payload);
                }
            },
            Err(_) => {
                let _ = app.emit("clippr-progress", json!({"type": "log", "message": trimmed}));
            }
        }
    }

    let status = child.wait().await.map_err(|error| error.to_string())?;
    let stderr_text = stderr_task.await.unwrap_or_default();
    let outcome = outcome.ok_or_else(|| {
        let detail = stderr_text.trim();
        if detail.is_empty() {
            format!("The clippr backend exited with {status} before returning a result.")
        } else {
            detail.to_string()
        }
    })?;

    if outcome.get("ok").and_then(|value| value.as_bool()) == Some(false) {
        return Err(outcome
            .get("error")
            .and_then(|value| value.as_str())
            .unwrap_or("The clippr backend failed.")
            .to_string());
    }
    if !status.success() {
        return Err(stderr_text.trim().to_string());
    }
    Ok(outcome.get("data").cloned().unwrap_or_else(|| json!({})))
}

#[tauri::command]
async fn app_status(app: AppHandle) -> Result<Value, String> {
    run_python(&app, vec!["status".into()]).await
}

#[tauri::command]
async fn ensure_tools(app: AppHandle) -> Result<Value, String> {
    run_python(&app, vec!["ensure-tools".into()]).await
}

#[tauri::command]
async fn parse_demo(app: AppHandle, path: String) -> Result<Value, String> {
    run_python(&app, vec!["parse".into(), path]).await
}

#[tauri::command]
async fn generate_clip(
    app: AppHandle,
    demo_path: String,
    highlight: Value,
    tickrate: f64,
    lead_in: f64,
    lead_out: f64,
    output_dir: String,
) -> Result<Value, String> {
    clear_cancel();
    let jobs = project_root().join("python").join(".jobs");
    fs::create_dir_all(&jobs).map_err(|error| error.to_string())?;
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or(0);
    let job_path = jobs.join(format!("job-{stamp}.json"));
    let job = json!({
        "demo_path": demo_path,
        "highlight": highlight,
        "tickrate": tickrate,
        "lead_in": lead_in,
        "lead_out": lead_out,
        "output_dir": output_dir,
    });
    fs::write(&job_path, serde_json::to_vec(&job).map_err(|error| error.to_string())?)
        .map_err(|error| error.to_string())?;
    let result = run_python(&app, vec!["generate".into(), job_path.display().to_string()]).await;
    let _ = fs::remove_file(&job_path);
    result
}

#[tauri::command]
fn cancel_job() -> Result<(), String> {
    let home = clippr_home();
    let _ = fs::create_dir_all(&home);
    fs::write(home.join("cancel"), b"1").map_err(|error| error.to_string())?;
    let active = home.join("active.json");
    if let Ok(text) = fs::read_to_string(&active) {
        if let Ok(value) = serde_json::from_str::<Value>(&text) {
            for key in ["cs2", "hlae"] {
                if let Some(pid) = value.get(key).and_then(|item| item.as_u64()) {
                    let mut command = std::process::Command::new("taskkill");
                    command.args(["/PID", &pid.to_string(), "/T", "/F"]);
                    #[cfg(windows)]
                    hide_console(&mut command);
                    let _ = command.output();
                }
            }
        }
    }
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            app_status,
            ensure_tools,
            parse_demo,
            generate_clip,
            cancel_job
        ])
        .run(tauri::generate_context!())
        .expect("clippr failed to start");
}
