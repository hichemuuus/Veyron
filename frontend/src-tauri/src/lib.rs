pub mod launcher;
pub mod tray;
pub mod updater;
pub mod config;

use tauri::{Emitter, Manager};
use launcher::BackendLauncher;
use tray::VeyronTray;
use config::AppConfig;
use updater::UpdateManager;
use std::sync::{Arc, Mutex, atomic::{AtomicBool, Ordering}};

mod http; // Custom HTTP commands replacing tauri-plugin-http

pub struct AppState {
    pub launcher: Arc<Mutex<BackendLauncher>>,
    pub backend_started: Arc<AtomicBool>,
    pub shutting_down: Arc<AtomicBool>,
}

#[tauri::command]
fn get_backend_status(state: tauri::State<AppState>) -> Result<String, String> {
    let launcher = state.launcher.lock().map_err(|e| e.to_string())?;
    Ok(format!("{}", launcher.is_running()))
}

#[tauri::command]
async fn restart_backend(app: tauri::AppHandle, state: tauri::State<'_, AppState>) -> Result<(), String> {
    let backend_started = state.backend_started.clone();
    {
        let mut launcher = state.launcher.lock().map_err(|e| e.to_string())?;
        launcher.stop();
    }
    backend_started.store(false, Ordering::SeqCst);
    let app_clone = app.clone();
    let launcher_clone = state.launcher.clone();
    let started_clone = backend_started.clone();
    std::thread::spawn(move || {
        if let Ok(mut guard) = launcher_clone.lock() {
            let _ = app_clone.emit("backend-status", "starting");
            match guard.start(&app_clone) {
                Ok(()) => {
                    started_clone.store(true, Ordering::SeqCst);
                }
                Err(e) => {
                    log::error!("Backend restart failed: {}", e);
                    let _ = app_clone.emit("backend-status", "error");
                }
            }
        }
    });
    Ok(())
}

#[tauri::command]
fn get_app_config() -> Result<AppConfig, String> {
    Ok(AppConfig::load())
}

#[tauri::command]
fn save_app_config(config: AppConfig) -> Result<(), String> {
    config.save()
}

#[tauri::command]
fn get_backend_port(state: tauri::State<AppState>) -> Result<u16, String> {
    let launcher = state.launcher.lock().map_err(|e| e.to_string())?;
    Ok(launcher.backend_port)
}

#[tauri::command]
fn get_backend_pid(state: tauri::State<AppState>) -> Result<Option<u32>, String> {
    let launcher = state.launcher.lock().map_err(|e| e.to_string())?;
    Ok(launcher.child_pid())
}

pub fn run() {
    env_logger::Builder::from_env(
        env_logger::Env::default().default_filter_or("info")
    )
    .format_timestamp_secs()
    .init();

    log::info!("[STARTUP] Veyron Desktop v{} starting", env!("CARGO_PKG_VERSION"));

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .setup(|app| {
            log::info!("[STARTUP] Tauri setup() called");
            let t0 = std::time::Instant::now();
            let handle = app.handle().clone();

            log::info!("[STARTUP] Creating main window at t={:?}", t0.elapsed());
            let win = handle.get_webview_window("main").ok_or("main window not found")?;
            win.set_title("Veyron AI")?;
            log::info!("[STARTUP] Main window created at t={:?}", t0.elapsed());

            // Backend launcher state
            let launcher = Arc::new(Mutex::new(BackendLauncher::new()));
            let backend_started = Arc::new(AtomicBool::new(false));
            let shutting_down = Arc::new(AtomicBool::new(false));
            let state = AppState {
                launcher: launcher.clone(),
                backend_started: backend_started.clone(),
                shutting_down: shutting_down.clone(),
            };
            handle.manage(state);

            // Update manager state
            let update_manager = UpdateManager::new();
            handle.manage(update_manager);

            log::info!("[STARTUP] Creating tray at t={:?}", t0.elapsed());
            VeyronTray::create(&handle)?;
            log::info!("[STARTUP] Tray created at t={:?}", t0.elapsed());

            // Start backend in background
            let h_launcher = handle.clone();
            let l_launcher = launcher.clone();
            let b_started = backend_started.clone();
            log::info!("[STARTUP] Spawning backend thread at t={:?}", t0.elapsed());
            std::thread::spawn(move || {
                log::info!("[STARTUP] Backend thread started at t={:?}", t0.elapsed());
                let _ = h_launcher.emit("backend-status", "starting");
                if let Ok(mut guard) = l_launcher.lock() {
                    log::info!("[STARTUP] Lock acquired, calling guard.start() at t={:?}", t0.elapsed());
                    if let Err(e) = guard.start(&h_launcher) {
                        log::error!("[STARTUP] Backend start FAILED: {} at t={:?}", e, t0.elapsed());
                        let _ = h_launcher.emit("backend-status", "error");
                    } else {
                        log::info!("[STARTUP] Backend started successfully at t={:?}", t0.elapsed());
                        b_started.store(true, Ordering::SeqCst);
                    }
                } else {
                    log::error!("[STARTUP] Failed to acquire launcher lock at t={:?}", t0.elapsed());
                }
            });

            // Check for updates on startup (after 5s delay)
            let h_update = handle.clone();
            std::thread::spawn(move || {
                std::thread::sleep(std::time::Duration::from_secs(5));
                log::info!("[STARTUP] Checking for updates at t={:?}", t0.elapsed());
                let rt = tokio::runtime::Runtime::new().unwrap();
                rt.block_on(async {
                    let version = updater::check_for_update(&h_update).await;
                    match version {
                        Ok(Some(v)) => {
                            log::info!("[STARTUP] Update available: v{} via check_for_update", v);
                            let _ = h_update.emit("update-available", &v);
                        }
                        Ok(None) => log::info!("[STARTUP] No update available"),
                        Err(e) => log::warn!("[STARTUP] Update check failed: {}", e),
                    }
                });
            });

            log::info!("[STARTUP] Tauri setup() complete at t={:?}", t0.elapsed());
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                // Only handle close on the main window
                if window.label() != "main" {
                    return;
                }
                let app_handle = window.app_handle();
                let state = app_handle.state::<AppState>();

                // Prevent double-close
                if state.shutting_down.load(Ordering::SeqCst) {
                    return;
                }
                state.shutting_down.store(true, Ordering::SeqCst);
                api.prevent_close();

                log::info!("Window close requested, shutting down backend...");
                let _ = app_handle.emit("backend-status", "shutting_down");

                // Stop the backend launcher gracefully
                match state.launcher.lock() {
                    Ok(mut launcher) => {
                        launcher.shutdown();
                        log::info!("Backend shut down on window close");
                    }
                    Err(e) => {
                        log::error!("Failed to lock launcher on close: {}", e);
                    }
                }

                // Close window (CloseRequested will fire again but shutting_down is true)
                let _ = window.close();
            }
        })
        .invoke_handler(tauri::generate_handler![
            get_backend_status,
            restart_backend,
            get_app_config,
            save_app_config,
            get_backend_port,
            get_backend_pid,
            updater::check_update,
            updater::install_update,
            updater::get_update_status,
            updater::cancel_download,
            updater::restart_app,
            updater::get_app_version,
            http::http_fetch,
        ])
        .build(tauri::generate_context!())
        .expect("error while building Veyron Desktop")
        .run(|app_handle, event| {
            if let tauri::RunEvent::Exit = event {
                log::info!("App exit event received, cleaning up backend");
                if let Some(state) = app_handle.try_state::<AppState>() {
                    match state.launcher.lock() {
                        Ok(mut launcher) => {
                            launcher.shutdown();
                            log::info!("Backend shut down on app exit");
                        }
                        Err(e) => {
                            log::error!("Failed to lock launcher on exit: {}", e);
                        }
                    }
                }
            }
        });
}
