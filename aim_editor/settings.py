"""
Wrapper tipis buat QSettings, satu-satunya tempat plugin nyimpen/baca setting
yang persisten antar sesi QGIS (base URL REST API, dkk). Sengaja dipisah dari
modul lain biar gampang di-mock pas unit test (lihat Tahap 6.5 implementation-
plan.md) dan biar semua kode yang butuh baca/tulis setting lewat satu pintu
aja -- ga ada QSettings() dipanggil langsung dari file lain.

CATATAN: ini BUKAN tempat nyimpen kredensial (token/password DB) -- itu tetep
lewat QgsAuthManager (lihat auth_manager.py). QSettings di sini cuma buat
setting non-rahasia kayak base URL API, yang emang wajar keliatan plaintext
di file config QGIS.
"""

from qgis.PyQt.QtCore import QSettings

# Namespace/key QSettings. Pola "AimEditor/<nama>" biar ga bentrok sama
# plugin lain yang mungkin pake QSettings juga (QSettings itu shared
# antar semua plugin dalam satu profile QGIS).
_SETTINGS_GROUP = "AimEditor"
_KEY_BASE_URL = f"{_SETTINGS_GROUP}/base_url"

# Default kalo user belom pernah isi apa-apa. Ganti sesuai environment
# default organisasi kalo perlu (dev/staging/prod beda mesin/URL).
DEFAULT_BASE_URL = "http://localhost:8080/api/v1"


def get_base_url() -> str:
    """Baca base URL REST API yang tersimpan. Balikin DEFAULT_BASE_URL
    kalo belom pernah di-set (first run)."""
    settings = QSettings()
    return settings.value(_KEY_BASE_URL, DEFAULT_BASE_URL, type=str)


def set_base_url(base_url: str) -> None:
    """Simpen base URL baru, dipanggil abis user isi/ubah field Server URL
    di LoginDialog. Persisten across sesi QGIS berikutnya."""
    settings = QSettings()
    settings.setValue(_KEY_BASE_URL, base_url.strip())
