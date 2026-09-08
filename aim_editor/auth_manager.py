"""
Wrapper buat QgsAuthManager, tugasnya nyimpen kredensial role PostgreSQL yang
didapet dari endpoint /db-credentials.

Kredensial ini GA BOLEH nyentuh file config biasa atau variabel Python yang
nyimpen lebih lama dari alur login itu sendiri. Langsung masuk ke database
auth QGIS yang udah terenkripsi (qgis-auth.db, AES, dikunci pake master
password QGIS user). Layer PostGIS wajib dibuka pake
`QgsDataSourceUri.setAuthConfigId(config_id)`, BUKAN `setUsername`/
`setPassword` manual, biar password ga pernah keliatan plaintext di
Layer Properties > Source atau ke-save ke file proyek (.qgz/.qgs).
"""

from typing import Optional

from qgis.core import (
    QgsApplication,
    QgsAuthMethodConfig,
    QgsMessageLog,
    Qgis,
)

AUTH_CONFIG_NAME = "aim_editor_pg_session"
LOG_TAG = "AIM Editor"


class AuthConfigManager:
    """Ngurusin satu QgsAuthMethodConfig buat sesi kredensial PostGIS plugin
    yang lagi aktif. Sengaja cuma pegang SATU config_id per waktu (bukan
    banyak), soalnya kredensial yang kita simpen ini untuk satu sesi user
    yang lagi login, bukan multi-sesi sekaligus."""

    def __init__(self):
        self._auth_manager = QgsApplication.authManager()
        self._config_id: Optional[str] = None

    @property
    def config_id(self) -> Optional[str]:
        return self._config_id

    def store_credentials(self, host: str, port: int, dbname: str,
                           user: str, password: str) -> str:
        """Bikin auth config PostgreSQL baru, balikin config_id-nya.

        Parameter host/port/dbname sengaja diterima tapi ga disimpen di
        config ini -- itu bagian dari data source URI layer (lihat
        layer_manager.py nanti), bukan tanggung jawab auth config. Diterima
        di sini cuma biar caller bisa log/tracing kalo perlu.
        """
        config = QgsAuthMethodConfig()
        config.setName(AUTH_CONFIG_NAME)
        config.setMethod("Basic")  # metode auth "Basic" bawaan QGIS = username/password
        config.setConfig("username", user)
        config.setConfig("password", password)

        ok = self._auth_manager.storeAuthenticationConfig(config)
        if not ok or not config.id():
            raise RuntimeError("Gagal nyimpen kredensial ke QGIS Authentication Manager")

        self._config_id = config.id()
        QgsMessageLog.logMessage(
            f"Auth config {self._config_id} berhasil disimpen buat sesi user", LOG_TAG, Qgis.Info
        )
        return self._config_id

    def update_credentials(self, user: str, password: str) -> None:
        """Refresh password di config yang udah ada (dipake pas perpanjangan
        sesi / session renewal). Layer yang udah pake authcfg id ini bakal
        otomatis pake kredensial baru pas nyoba connect lagi -- ga perlu
        reload atau nambahin ulang layer-nya."""
        if not self._config_id:
            raise RuntimeError("Belum ada auth config yang bisa di-update")

        config = QgsAuthMethodConfig()
        if not self._auth_manager.loadAuthenticationConfig(self._config_id, config, True):
            raise RuntimeError(f"Gagal load auth config {self._config_id} buat di-update")

        config.setConfig("username", user)
        config.setConfig("password", password)

        ok = self._auth_manager.updateAuthenticationConfig(config)
        if not ok:
            raise RuntimeError("Gagal update kredensial di QGIS Authentication Manager")

        QgsMessageLog.logMessage(
            f"Auth config {self._config_id} berhasil di-refresh", LOG_TAG, Qgis.Info
        )

    def remove_credentials(self) -> None:
        """Hapus auth config-nya total. WAJIB dipanggil pas plugin di-unload,
        user logout, atau QGIS ditutup -- biar kredensial DB ga nyangkut di
        qgis-auth.db lebih lama dari masa sesi yang seharusnya."""
        if self._config_id:
            self._auth_manager.removeAuthenticationConfig(self._config_id)
            QgsMessageLog.logMessage(
                f"Auth config {self._config_id} udah dihapus", LOG_TAG, Qgis.Info
            )
            self._config_id = None
