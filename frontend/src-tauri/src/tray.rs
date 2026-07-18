use crate::AppState;
use tauri::{
    AppHandle,
    Manager,
    Emitter,
    menu::{MenuBuilder, MenuItemBuilder, PredefinedMenuItem},
    tray::{TrayIconBuilder, MouseButton, MouseButtonState, TrayIconEvent},
    Runtime,
};

pub struct VeyronTray;

impl VeyronTray {
    pub fn create<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<()> {
        let open = MenuItemBuilder::with_id("open", "Open Veyron").build(app)?;
        let separator = PredefinedMenuItem::separator(app)?;
        let restart = MenuItemBuilder::with_id("restart", "Restart AI Engine").build(app)?;
        let stop = MenuItemBuilder::with_id("stop", "Stop AI Engine").build(app)?;
        let check_updates = MenuItemBuilder::with_id("check_updates", "Check for Updates...").build(app)?;
        let separator2 = PredefinedMenuItem::separator(app)?;
        let quit = MenuItemBuilder::with_id("quit", "Quit").build(app)?;

        let menu = MenuBuilder::new(app)
            .item(&open)
            .item(&separator)
            .item(&restart)
            .item(&stop)
            .item(&check_updates)
            .item(&separator2)
            .item(&quit)
            .build()?;

        let tray_icon = app.default_window_icon().cloned();
        let mut tray = TrayIconBuilder::new()
            .tooltip("Veyron AI")
            .menu(&menu);
        if let Some(ref icon) = tray_icon {
            tray = tray.icon(icon.clone());
        }
        tray
            .on_menu_event(move |app, event| {
                match event.id().as_ref() {
                    "open" => {
                        if let Some(win) = app.get_webview_window("main") {
                            let _ = win.show();
                            let _ = win.set_focus();
                        }
                    }
                    "restart" => {
                        log::info!("Restarting AI engine...");
                        let _ = app.emit("engine-command", "restart");
                    }
                    "stop" => {
                        log::info!("Stopping AI engine...");
                        let _ = app.emit("engine-command", "stop");
                    }
                    "check_updates" => {
                        log::info!("Checking for updates from tray...");
                        let _ = app.emit("engine-command", "check-for-updates");
                    }
                    "quit" => {
                        log::info!("Quitting Veyron...");
                        let state = app.state::<AppState>();
                        match state.launcher.lock() {
                            Ok(mut launcher) => {
                                launcher.shutdown();
                                log::info!("Backend shut down before quit");
                            }
                            Err(e) => {
                                log::error!("Failed to lock launcher on quit: {}", e);
                            }
                        }
                        app.exit(0);
                    }
                    _ => {}
                }
            })
            .on_tray_icon_event(|tray, event| {
                if let TrayIconEvent::Click {
                    button: MouseButton::Left,
                    button_state: MouseButtonState::Up,
                    ..
                } = event
                {
                    let app = tray.app_handle();
                    if let Some(win) = app.get_webview_window("main") {
                        let _ = win.show();
                        let _ = win.set_focus();
                    }
                }
            })
            .build(app)?;

        Ok(())
    }
}
