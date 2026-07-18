# Release Checklist

## Quick Start (automated)
```bash
# Validate environment
python scripts/verify_environment.py

# Dry-run release (preview all steps)
python scripts/release.py --patch --dry-run

# Live release (bump patch, build, sign, push to GitHub)
python scripts/release.py --patch --push
```

## Pre-Release
- [ ] Backend stable — all tests pass (821+)
- [ ] Backend environment verified (`python scripts/verify_environment.py`)
- [ ] Frontend builds without errors (`npm run build`)
- [ ] Tauri desktop build succeeds (`npm run tauri:build`)
- [ ] Installer generates successfully (NSIS)
- [ ] Version numbers consistent (checked by `release.py`)
- [ ] CHANGELOG.md updated
- [ ] Documentation complete and accurate
- [ ] Sidecar binary rebuilt from `.venv` Python (`python scripts/build_backend.py`)
- [ ] Sidecar bundled as Tauri resource

## Updater / Signing
- [ ] Updater private key present at `~/.config/veyron/veyron-updater-key.private` (or CI secret `UPDATER_PRIVATE_KEY`)
- [ ] Updater public key matches `tauri.conf.json` `plugins.updater.pubkey`
- [ ] Installer signed via `release.py` (invokes `sign_update.py`)
- [ ] `latest.json` generated and uploaded as release asset
- [ ] Update URL matches `tauri.conf.json` endpoint
- [ ] Update test passed (17 tests in `test_update.py`)
- [ ] Upgrade test: install v1.0.0 → bump to v1.0.1 → build → verify `latest.json` → test updater

## Security
- [ ] No secrets committed
- [ ] `.gitignore` audit complete (`veyron-updater-key.private` excluded)
- [ ] Security policies reviewed
- [ ] Dependency vulnerabilities checked

## Documentation
- [ ] README.md up to date
- [ ] INSTALLATION.md accurate
- [ ] ARCHITECTURE.md reflects current state
- [ ] CHANGELOG.md complete
- [ ] TROUBLESHOOTING.md current

## Release
- [ ] Tag version (`git tag vX.Y.Z`)
- [ ] Push tag to GitHub (triggers CI/CD)
- [ ] GitHub Actions CI/CD runs (build → sign → upload)
- [ ] Release artifacts uploaded (installer + `latest.json` + `.sig`)
- [ ] Release notes published (auto-generated from tag)

## Post-Release
- [ ] Verify installer on clean machine
- [ ] Test update from previous version (install v1.0.0 → launch → should find v1.0.1)
- [ ] Monitor issue tracker for feedback
- [ ] Update ROADMAP.md
