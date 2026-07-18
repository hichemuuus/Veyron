use std::io::{BufRead, BufReader, Read};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter, Manager};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

pub struct BackendLauncher {
    child: Option<Child>,
    running: Arc<AtomicBool>,
    pub backend_port: u16,
}

impl BackendLauncher {
    pub fn new() -> Self {
        Self {
            child: None,
            running: Arc::new(AtomicBool::new(false)),
            backend_port: 8000,
        }
    }

    pub fn is_running(&self) -> bool {
        self.running.load(Ordering::SeqCst)
    }

    pub fn child_pid(&self) -> Option<u32> {
        self.child.as_ref().map(|c| c.id())
    }

    fn diag_write(msg: &str) {
        let diag_path = std::env::temp_dir().join("veyron-diag.log");
        let _ = std::fs::write(&diag_path, msg);
    }

    pub fn start(&mut self, app: &AppHandle) -> Result<(), String> {
        let t0 = Instant::now();
        log::info!("[STARTUP] BackendLauncher::start() called at t={:?}", t0.elapsed());

        if self.is_running() {
            log::info!("[STARTUP] Already running, returning early");
            return Ok(());
        }

        // ── Step 1: Resolve resource_dir ──
        match app.path().resource_dir() {
            Ok(rd) => {
                let sidecar = rd.join("binaries").join("veyron-backend-x86_64-pc-windows-msvc.exe");
                log::info!("[STARTUP] resource_dir={:?}", rd);
                log::info!("[STARTUP] exe={:?}", std::env::current_exe().unwrap_or_default());
                log::info!("[STARTUP] sidecar_path={:?}", sidecar);
                log::info!("[STARTUP] sidecar_exists={}", sidecar.exists());
                Self::diag_write(&format!(
                    "resource_dir: {:?}\nexe: {:?}\nsidecar: {:?}\nsidecar_exists: {}\nt={:?}\n",
                    rd,
                    std::env::current_exe().unwrap_or_default(),
                    sidecar,
                    sidecar.exists(),
                    t0.elapsed(),
                ));
            }
            Err(e) => {
                log::error!("[STARTUP] resource_dir FAILED: {}", e);
                Self::diag_write(&format!("resource_dir FAILED: {}\n", e));
            }
        }

        // ── Step 2: Spawn backend process ──
        log::info!("[STARTUP] Spawning backend at t={:?}", t0.elapsed());
        let child = match self.spawn_backend(app) {
            Ok(c) => c,
            Err(e) => {
                log::error!("[STARTUP] spawn_backend FAILED: {} (at t={:?})", e, t0.elapsed());
                Self::diag_write(&format!("spawn_backend FAILED: {}\n", e));
                return Err(e);
            }
        };
        log::info!("[STARTUP] Backend spawned PID={} at t={:?}", child.id(), t0.elapsed());
        self.child = Some(child);
        self.running.store(true, Ordering::SeqCst);

        // ── Step 3: Wait for health endpoint ──
        let port = self.backend_port;
        let max_retries = 8;
        let mut delay_ms = 500u64;
        let mut started = false;
        let client = reqwest::blocking::Client::builder()
            .timeout(Duration::from_secs(2))
            .build()
            .expect("valid reqwest client");

        log::info!("[STARTUP] Health polling starting at t={:?} (port={}, max_retries={})", t0.elapsed(), port, max_retries);
        for attempt in 1..=max_retries {
            // Check if child has exited
            let child_exit_code: Option<i32> = self.child.as_mut().and_then(|c| c.try_wait().ok().flatten()).map(|e| e.code().unwrap_or(-1));
            if let Some(code) = child_exit_code {
                log::warn!("[STARTUP] Backend child process exited prematurely with code={:?} at t={:?}", Some(code), t0.elapsed());
                let msg = format!("Backend process exited with code {} before health check", code);
                self.running.store(false, Ordering::SeqCst);
                let _ = app.emit("backend-status", "error");
                return Err(msg);
            }

            match client
                .get(&format!("http://127.0.0.1:{}/api/health", port))
                .send()
            {
                Ok(resp) if resp.status().is_success() => {
                    let elapsed = t0.elapsed();
                    log::info!("[STARTUP] Health OK attempt={} at t={:?}", attempt, elapsed);
                    started = true;
                    break;
                }
                Ok(resp) => {
                    log::debug!("[STARTUP] Health attempt {} returned HTTP {} at t={:?}", attempt, resp.status(), t0.elapsed());
                }
                Err(e) => {
                    log::debug!("[STARTUP] Health attempt {} failed: {} at t={:?}", attempt, e, t0.elapsed());
                }
            }

            if attempt < max_retries {
                std::thread::sleep(Duration::from_millis(delay_ms));
                delay_ms = (delay_ms * 2).min(4000);
            }
        }

        // ── Step 4: Final result ──
        self.monitor_health(app);

        if started {
            Self::diag_write(&format!("Backend started successfully at t={:?}\n", t0.elapsed()));
            log::info!("[STARTUP] SUCCESS at t={:?}", t0.elapsed());
            let _ = app.emit("backend-status", "running");
            Ok(())
        } else {
            let elapsed = t0.elapsed();
            self.running.store(false, Ordering::SeqCst);
            let msg = format!("Backend failed to start after {} attempts (elapsed={:?})", max_retries, elapsed);
            Self::diag_write(&format!("{}\n", msg));
            log::error!("[STARTUP] FAILURE: {} at t={:?}", msg, elapsed);

            // Log child exit code if available
            let exit_code = self.child.as_mut().and_then(|c| c.try_wait().ok().flatten()).map(|e| e.code().unwrap_or(-1));
            if let Some(code) = exit_code {
                log::error!("[STARTUP] Backend child exit code: {}", code);
                Self::diag_write(&format!("Backend exit code: {}\n", code));
            }

            let _ = app.emit("backend-status", "error");
            Err(msg)
        }
    }

    pub fn stop(&mut self) {
        self.running.store(false, Ordering::SeqCst);
        if let Some(mut child) = self.child.take() {
            #[cfg(windows)]
            {
                let _ = Command::new("taskkill")
                    .args(["/PID", &child.id().to_string(), "/F", "/T"])
                    .output();
            }
            #[cfg(not(windows))]
            {
                let _ = child.kill();
            }
            let _ = child.wait();
            log::info!("Backend stopped");
        }
    }

    pub fn wait(&mut self) {
        if let Some(mut child) = self.child.take() {
            let _ = child.wait();
        }
    }

    /// Graceful shutdown: wait up to 2s for the child to exit on its own,
    /// then force kill if it hasn't exited.
    pub fn wait_for_shutdown(&mut self) {
        if let Some(mut child) = self.child.take() {
            let deadline = Instant::now() + Duration::from_secs(2);
            loop {
                match child.try_wait() {
                    Ok(Some(_)) => {
                        log::info!("Backend exited gracefully");
                        return;
                    }
                    Ok(None) => {
                        if Instant::now() >= deadline {
                            break;
                        }
                        std::thread::sleep(Duration::from_millis(100));
                    }
                    Err(e) => {
                        log::warn!("Error waiting for backend child: {}", e);
                        break;
                    }
                }
            }
            log::warn!("Backend did not exit within timeout, force killing");
            #[cfg(windows)]
            {
                let _ = Command::new("taskkill")
                    .args(["/PID", &child.id().to_string(), "/F", "/T"])
                    .output();
            }
            #[cfg(not(windows))]
            {
                let _ = child.kill();
            }
            let _ = child.wait();
            log::info!("Backend force killed");
        }
    }

    /// Full shutdown sequence: signal health monitor, then wait gracefully,
    /// then force kill if necessary.
    pub fn shutdown(&mut self) {
        self.running.store(false, Ordering::SeqCst);
        self.wait_for_shutdown();
        log::info!("Backend shutdown complete");
    }

    fn spawn_backend(&self, _app: &AppHandle) -> Result<Child, String> {
        // dev: use system Python / uvicorn
        #[cfg(debug_assertions)]
        {
            self.spawn_uvicorn()
        }

        // release (Windows): try bundled sidecar first, then fall back to uvicorn
        #[cfg(all(not(debug_assertions), target_os = "windows"))]
        {
            self.spawn_sidecar(_app).or_else(|_| self.spawn_uvicorn())
        }

        // release (non-Windows): fall back to uvicorn
        #[cfg(all(not(debug_assertions), not(target_os = "windows")))]
        {
            self.spawn_uvicorn()
        }
    }

    fn new_command(program: &str) -> Command {
        let mut cmd = Command::new(program);
        #[cfg(windows)]
        cmd.creation_flags(CREATE_NO_WINDOW);
        cmd
    }

    fn spawn_uvicorn(&self) -> Result<Child, String> {
        let t0 = Instant::now();
        log::info!("[SPAWN_UVICORN] Starting at t={:?}", t0.elapsed());

        let backend_dir = match find_backend_dir() {
            Ok(d) => {
                log::info!("[SPAWN_UVICORN] backend_dir={:?}", d);
                d
            }
            Err(e) => {
                log::error!("[SPAWN_UVICORN] find_backend_dir FAILED: {}", e);
                return Err(e);
            }
        };

        log::info!("[SPAWN_UVICORN] Starting uvicorn from: {:?}", backend_dir);

        match Self::new_command("uvicorn")
            .args([
                "veyron.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                &self.backend_port.to_string(),
                "--log-level",
                "info",
            ])
            .env("PYTHONPATH", backend_dir.to_str().unwrap_or("backend"))
            .current_dir(&backend_dir)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
        {
            Ok(mut child) => {
                log::info!("[SPAWN_UVICORN] Process spawned PID={} at t={:?}", child.id(), t0.elapsed());
                Self::pipe_logs(child.stdout.take(), "backend");
                Self::pipe_logs(child.stderr.take(), "backend");
                Ok(child)
            }
            Err(e) => {
                let msg = format!(
                    "Cannot start uvicorn: {}\nMake sure uvicorn is installed (pip install uvicorn fastapi)",
                    e
                );
                log::error!("[SPAWN_UVICORN] {}", msg);
                Err(msg)
            }
        }
    }

    #[cfg(all(not(debug_assertions), target_os = "windows"))]
    fn spawn_sidecar(&self, app: &AppHandle) -> Result<Child, String> {
        let t0 = Instant::now();
        log::info!("[SPAWN_SIDECAR] Starting at t={:?}", t0.elapsed());

        let resource_dir = app
            .path()
            .resource_dir()
            .map_err(|e| {
                log::error!("[SPAWN_SIDECAR] Cannot resolve resource dir: {}", e);
                format!("Cannot resolve resource dir: {}", e)
            })?;

        log::info!("[SPAWN_SIDECAR] resource_dir={:?}", resource_dir);

        let sidecar_path = resource_dir
            .join("binaries")
            .join("veyron-backend-x86_64-pc-windows-msvc.exe");

        log::info!("[SPAWN_SIDECAR] sidecar_path={:?}", sidecar_path);
        log::info!("[SPAWN_SIDECAR] sidecar_exists={}", sidecar_path.exists());

        if !sidecar_path.exists() {
            let msg = format!("Sidecar not found at: {:?}", sidecar_path);
            log::error!("[SPAWN_SIDECAR] {}", msg);
            return Err(msg);
        }

        let sidecar_str = match sidecar_path.to_str() {
            Some(s) => s,
            None => {
                let msg = format!("Non-UTF8 path: {:?}", sidecar_path);
                log::error!("[SPAWN_SIDECAR] {}", msg);
                return Err(msg);
            }
        };

        log::info!("[SPAWN_SIDECAR] Launching: {} --port {}", sidecar_str, self.backend_port);

        match Self::new_command(sidecar_str)
            .args(["--port", &self.backend_port.to_string()])
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
        {
            Ok(mut child) => {
                log::info!("[SPAWN_SIDECAR] Process spawned PID={} at t={:?}", child.id(), t0.elapsed());
                Self::pipe_logs(child.stdout.take(), "sidecar");
                Self::pipe_logs(child.stderr.take(), "sidecar");
                Ok(child)
            }
            Err(e) => {
                let msg = format!("Failed to launch sidecar: {} (path={:?})", e, sidecar_str);
                log::error!("[SPAWN_SIDECAR] {}", msg);
                Err(msg)
            }
        }
    }

    fn pipe_logs<T: Read + Send + 'static>(pipe: Option<T>, label: &'static str) {
        if let Some(reader) = pipe {
            std::thread::spawn(move || {
                let buf = BufReader::new(reader);
                for line in buf.lines() {
                    if let Ok(text) = line {
                        log::info!("[{}] {}", label, text);
                    }
                }
            });
        }
    }

    fn monitor_health(&self, app: &AppHandle) {
        let running = self.running.clone();
        let handle = app.clone();
        let port = self.backend_port;

        std::thread::spawn(move || {
            let client = reqwest::blocking::Client::builder()
                .timeout(Duration::from_secs(5))
                .build()
                .expect("valid reqwest client");

            let mut was_healthy = true;
            let mut consecutive_failures = 0u32;
            loop {
                if !running.load(Ordering::SeqCst) {
                    break;
                }
                std::thread::sleep(Duration::from_secs(15));
                if !running.load(Ordering::SeqCst) {
                    break;
                }
                match client
                    .get(&format!("http://127.0.0.1:{}/api/health", port))
                    .send()
                {
                    Ok(resp) if resp.status().is_success() => {
                        consecutive_failures = 0;
                        if !was_healthy {
                            log::info!("Backend health restored");
                            let _ = handle.emit("backend-status", "running");
                        }
                        was_healthy = true;
                    }
                    _ => {
                        consecutive_failures += 1;
                        if was_healthy {
                            log::warn!("Backend health check FAILED (x1)");
                            let _ = handle.emit("backend-status", "unhealthy");
                        }
                        was_healthy = false;
                        // After 3 consecutive failures (45s), mark as dead
                        if consecutive_failures >= 3 {
                            log::error!("Backend presumed dead after {} consecutive failures", consecutive_failures);
                            running.store(false, Ordering::SeqCst);
                            let _ = handle.emit("backend-status", "error");
                            break;
                        }
                    }
                }
            }
        });
    }
}

impl Drop for BackendLauncher {
    fn drop(&mut self) {
        self.stop();
    }
}

fn find_backend_dir() -> Result<std::path::PathBuf, String> {
    let candidates: Vec<std::path::PathBuf> = vec![
        {
            let mut cwd = std::env::current_dir().unwrap_or_default();
            cwd.pop();
            cwd.pop();
            cwd.join("backend")
        },
        std::path::PathBuf::from("backend"),
        std::path::PathBuf::from("../backend"),
    ];

    for candidate in &candidates {
        let candidate_v = candidate.join("veyron").join("main.py");
        if candidate_v.exists() {
            return Ok(candidate.clone());
        }
    }

    Err(format!(
        "Backend directory not found. Tried: {:?}",
        candidates.iter().map(|c| c.join("veyron").join("main.py")).collect::<Vec<_>>()
    ))
}
