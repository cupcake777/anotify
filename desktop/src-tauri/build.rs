fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "get_notifications",
            "update_config",
            "get_config",
            "clear_notifications",
            "verify_connection",
            "reconnect",
        ]),
    ))
    .expect("failed to build tauri app")
}
