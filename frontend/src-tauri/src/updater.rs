use serde::{Deserialize, Serialize};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};
use tauri::{AppHandle, Emitter};
use tauri_plugin_updater::UpdaterExt;

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct UpdateInfo {
    pub version: String,
    pub date: String,
    pub body: String,
    pub download_url: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub enum UpdateStatus {
    Idle,
    Checking,
    Available(UpdateInfo),
    Downloading { version: String, progress: f64 },
    Installing,
    Done,
    Failed(String),
}

impl Default for UpdateStatus {
    fn default() -> Self {
        Self::Idle
    }
}

pub struct UpdateManager {
    pub state: Arc<Mutex<UpdateStatus>>,
    pub cancel_flag: Arc<AtomicBool>,
}

impl UpdateManager {
    pub fn new() -> Self {
        Self {
            state: Arc::new(Mutex::new(UpdateStatus::Idle)),
            cancel_flag: Arc::new(AtomicBool::new(false)),
        }
    }
}

fn parse_semver(version: &str) -> Vec<u32> {
    version
        .trim_start_matches('v')
        .split('.')
        .filter_map(|part| part.parse::<u32>().ok())
        .collect()
}

/// Compare two version strings using semantic versioning rules.
/// Returns true if `latest` is strictly greater than `current`.
fn is_newer_version(latest: &str, current: &str) -> bool {
    let l = parse_semver(latest);
    let c = parse_semver(current);
    let max_len = l.len().max(c.len());
    for i in 0..max_len {
        let lv = l.get(i).copied().unwrap_or(0);
        let cv = c.get(i).copied().unwrap_or(0);
        if lv != cv {
            return lv > cv;
        }
    }
    false
}

#[tauri::command]
pub async fn check_update(
    app: AppHandle,
    manager: tauri::State<'_, UpdateManager>,
) -> Result<Option<UpdateInfo>, String> {
    {
        let mut s = manager.state.lock().map_err(|e| e.to_string())?;
        *s = UpdateStatus::Checking;
    }
    let _ = app.emit("update:status-changed", "checking");

    match app.updater() {
        Ok(updater) => match updater.check().await {
            Ok(Some(update)) => {
                let info = UpdateInfo {
                    version: update.version.clone(),
                    date: update
                        .date
                        .map(|d| d.to_string())
                        .unwrap_or_default(),
                    body: update.body.unwrap_or_default(),
                    download_url: update.download_url.to_string(),
                };
                {
                    let mut s = manager.state.lock().map_err(|e| e.to_string())?;
                    *s = UpdateStatus::Available(info.clone());
                }
                let _ = app.emit("update:status-changed", "available");
                log::info!("Update available: v{}", info.version);
                Ok(Some(info))
            }
            Ok(None) => {
                {
                    let mut s = manager.state.lock().map_err(|e| e.to_string())?;
                    *s = UpdateStatus::Idle;
                }
                let _ = app.emit("update:status-changed", "idle");
                log::info!("No update available");
                Ok(None)
            }
            Err(e) => {
                let msg = format!("Update check failed: {}", e);
                log::warn!("{}", msg);
                {
                    let mut s = manager.state.lock().map_err(|e| e.to_string())?;
                    *s = UpdateStatus::Failed(msg.clone());
                }
                let _ = app.emit("update:status-changed", "failed");
                check_github_releases().await
            }
        },
        Err(e) => {
            log::warn!("Updater plugin not available ({}), falling back to GitHub API", e);
            check_github_releases().await
        }
    }
}

#[tauri::command]
pub async fn install_update(
    app: AppHandle,
    manager: tauri::State<'_, UpdateManager>,
) -> Result<(), String> {
    let info = {
        let s = manager.state.lock().map_err(|e| e.to_string())?;
        match &*s {
            UpdateStatus::Available(info) => info.clone(),
            _ => return Err("No update available to install".to_string()),
        }
    };

    manager.cancel_flag.store(false, Ordering::SeqCst);

    {
        let mut s = manager.state.lock().map_err(|e| e.to_string())?;
        *s = UpdateStatus::Downloading {
            version: info.version.clone(),
            progress: 0.0,
        };
    }
    let _ = app.emit("update:status-changed", "downloading");

    let updater = app.updater().map_err(|e| e.to_string())?;
    let update = updater
        .check()
        .await
        .map_err(|e| e.to_string())?
        .ok_or_else(|| "Update no longer available".to_string())?;

    // Clone Arcs for use in closures
    let state = manager.state.clone();
    let cancel_flag = manager.cancel_flag.clone();
    let app_for_chunk = app.clone();
    let version_for_chunk = info.version.clone();

    let on_chunk = move |downloaded: usize, total: Option<u64>| {
        if cancel_flag.load(Ordering::SeqCst) {
            return;
        }
        let progress = total.map(|t| downloaded as f64 / t as f64).unwrap_or(0.0);
        if let Ok(mut s) = state.lock() {
            *s = UpdateStatus::Downloading {
                version: version_for_chunk.clone(),
                progress,
            };
        }
        let _ = app_for_chunk.emit("update:download-progress", progress);
    };

    let on_finish = || {};

    let bytes = update
        .download(on_chunk, on_finish)
        .await
        .map_err(|e| format!("Download failed: {}", e))?;

    // Re-check cancellation after download completes
    // (the on_chunk may not be called for the last chunk, so check here too)
    {
        let s = manager.state.lock().map_err(|e| e.to_string())?;
        if let UpdateStatus::Idle = &*s {
            return Err("Download cancelled by user".to_string());
        }
    }

    {
        let mut s = manager.state.lock().map_err(|e| e.to_string())?;
        *s = UpdateStatus::Installing;
    }
    let _ = app.emit("update:status-changed", "installing");

    update
        .install(bytes)
        .map_err(|e| format!("Install failed: {}", e))?;

    {
        let mut s = manager.state.lock().map_err(|e| e.to_string())?;
        *s = UpdateStatus::Done;
    }
    let _ = app.emit("update:status-changed", "done");

    log::info!(
        "Update v{} installed successfully. Restart to apply.",
        info.version
    );
    Ok(())
}

#[tauri::command]
pub fn get_update_status(
    manager: tauri::State<'_, UpdateManager>,
) -> Result<UpdateStatus, String> {
    let s = manager.state.lock().map_err(|e| e.to_string())?;
    Ok(s.clone())
}

#[tauri::command]
pub fn cancel_download(
    app: AppHandle,
    manager: tauri::State<'_, UpdateManager>,
) -> Result<(), String> {
    let mut s = manager.state.lock().map_err(|e| e.to_string())?;
    match &*s {
        UpdateStatus::Downloading { .. } => {
            manager.cancel_flag.store(true, Ordering::SeqCst);
            *s = UpdateStatus::Idle;
            let _ = app.emit("update:status-changed", "idle");
            log::info!("Download cancelled by user");
            Ok(())
        }
        _ => Err("No active download to cancel".to_string()),
    }
}

#[tauri::command]
pub async fn restart_app(app: AppHandle) -> Result<(), String> {
    log::info!("Restarting application...");
    app.restart();
    #[allow(unreachable_code)]
    Ok(())
}

#[tauri::command]
pub fn get_app_version() -> String {
    env!("CARGO_PKG_VERSION").to_string()
}

/// Simple startup check (no state management). Returns version string if update available.
pub async fn check_for_update(app: &AppHandle) -> Result<Option<String>, String> {
    match app.updater() {
        Ok(updater) => match updater.check().await {
            Ok(Some(update)) => {
                log::info!("Update found: v{}", update.version);
                Ok(Some(update.version.to_string()))
            }
            Ok(None) => Ok(None),
            Err(e) => {
                log::warn!("Updater check error: {}", e);
                Ok(None)
            }
        },
        Err(e) => {
            log::warn!("Updater plugin not available ({}), checking GitHub API", e);
            github_latest_version().await
        }
    }
}

async fn github_latest_version() -> Result<Option<String>, String> {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()
        .map_err(|e| e.to_string())?;
    let resp = client
        .get("https://api.github.com/repos/hichemuuus/Veyron/releases/latest")
        .header("User-Agent", "Veyron-Desktop/1.0")
        .send()
        .await
        .map_err(|e| format!("GitHub API error: {}", e))?;
    if !resp.status().is_success() {
        return Ok(None);
    }
    let release: Release = resp
        .json()
        .await
        .map_err(|e| format!("Parse error: {}", e))?;
    let current = current_version();
    let latest = release.tag_name.trim_start_matches('v');
    if is_newer_version(latest, current) {
        Ok(Some(latest.to_string()))
    } else {
        Ok(None)
    }
}

fn current_version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

#[derive(Debug, Serialize, Deserialize)]
struct Release {
    tag_name: String,
    html_url: String,
    body: Option<String>,
    published_at: String,
}

async fn check_github_releases() -> Result<Option<UpdateInfo>, String> {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()
        .map_err(|e| e.to_string())?;

    let resp = client
        .get("https://api.github.com/repos/hichemuuus/Veyron/releases/latest")
        .header("User-Agent", "Veyron-Desktop/1.0")
        .header("Accept", "application/vnd.github.v3+json")
        .send()
        .await
        .map_err(|e| format!("GitHub API error: {}", e))?;

    if !resp.status().is_success() {
        return Ok(None);
    }

    let release: Release = resp
        .json()
        .await
        .map_err(|e| format!("Parse error: {}", e))?;
    let current = current_version();
    let latest = release.tag_name.trim_start_matches('v');

    if is_newer_version(latest, current) {
        let version = latest.to_string();
        let info = UpdateInfo {
            version: version.clone(),
            date: release.published_at,
            body: release.body.unwrap_or_default(),
            download_url: format!(
                "https://github.com/hichemuuus/Veyron/releases/download/v{}/Veyron_{}_x64-setup.exe",
                version, version
            ),
        };
        log::info!("Update available via GitHub: v{}", version);
        Ok(Some(info))
    } else {
        Ok(None)
    }
}
