"""
Client tipis buat ngobrol ke REST API backend (backend-aim, Go/Gin) yang udah ada.
Backend ini pakai token PASETO v2 (mode local/symmetric = terenkripsi, bukan cuma
signed kayak JWT), jadi plugin GA PERLU dan GA BISA decode isi token-nya sendiri
(butuh symmetric key yang cuma dipegang server). Token diperlakukan sebagai bearer
token opaque aja, tinggal ditempel di header Authorization tiap request.

Skema di bawah ini SUDAH dicocokkan sama kode asli backend (bukan tebakan lagi):
- POST /auth/login  -> body {login_id, password}, response {token, user}
- GET  /me          -> endpoint yang UDAH ADA, berisi field `roles` dan `permissions`.
  Ga ada endpoint /me/rights terpisah, jangan bikin-bikin sendiri.
- GET  /db-credentials -> endpoint BARU, belum ada di backend, perlu ditambahin
  di sisi server (lihat docs/business-rules.md Bagian 3.2 buat detail desainnya).

Kalo backend berubah kontraknya (masih aktif dikembangin soalnya), cukup update
di sini aja, kelas ini yang jadi satu-satunya titik kontak ke REST API.
"""

from dataclasses import dataclass
from typing import Optional

import requests


class ApiError(Exception):
    """Dilempar kalo response dari REST API non-2xx atau bentuknya ga sesuai
    yang diharapkan (field hilang, JSON rusak, dll)."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class DbCredentials:
    """Kredensial role PostgreSQL yang dibalikin endpoint /db-credentials.
    Ini BUKAN kredensial akun aplikasi user, tapi kredensial role Postgres
    yang udah dipetakan dari permission user (lihat business-rules.md)."""

    host: str
    port: int
    dbname: str
    # Nama SCHEMA (bukan database) tempat tabel adhp/ADHPSurfaceArea berada.
    # WAJIB dipake pas setSchema() di QgsDataSourceUri -- JANGAN asumsi
    # "public", dikonfirmasi lewat percobaan langsung kalau tabel-tabel ini
    # nempatnya di schema yang namanya ngikutin user koneksi database backend,
    # bukan default public. Lihat docs/implementation-plan.md Tahap 3-4.
    schema: str
    user: str
    password: str
    expires_at: str  # timestamp ISO-8601, dipake buat cek kapan mesti refresh


class ApiClient:
    """Satu instance = satu sesi login. Simpan token di memori aja (bukan
    disk), soalnya token PASETO ini yang jadi kunci ke endpoint lain."""

    def __init__(self, base_url: str, timeout: int = 15):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._token: Optional[str] = None

    @property
    def token(self) -> Optional[str]:
        return self._token

    def set_token(self, token: str) -> None:
        """Dipake kalo token udah didapet dari luar (misal pas refresh sesi),
        biar ga perlu login ulang dari nol."""
        self._token = token

    def _auth_headers(self) -> dict:
        if not self._token:
            raise ApiError("Belum login: token belom ke-set")
        return {"Authorization": f"Bearer {self._token}"}

    def login(self, login_id: str, password: str) -> str:
        """
        POST /auth/login

        Request:  {"login_id": "...", "password": "..."}
        Response: {"token": "v2.local.xxxxx...", "user": {...}}

        Catatan: field-nya `login_id` (bukan `username`) karena di backend
        field ini nerima username ATAU email sekaligus. Token yang balik
        formatnya string PASETO asli (`v2.local...`), bukan JWT.
        """
        url = f"{self.base_url}/auth/login"
        try:
            resp = requests.post(
                url,
                json={"login_id": login_id, "password": password},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ApiError(f"Request login gagal: {exc}") from exc

        if resp.status_code != 200:
            raise ApiError(
                f"Login gagal ({resp.status_code}): {resp.text}",
                status_code=resp.status_code,
            )

        try:
            data = resp.json()
            token = data["token"]
        except (ValueError, KeyError) as exc:
            raise ApiError("Response login ga ada field 'token'") from exc

        self._token = token
        return token

    def get_me(self) -> dict:
        """
        GET /me  (Authorization: Bearer <token>)

        Endpoint ini UDAH ADA di backend (bukan bikinan baru), jangan
        panggil /me/rights soalnya ga ada endpoint itu. Response mencakup
        (field yang relevan buat plugin ini):

            {
              "id": "uuid",
              "username": "...",
              "roles": [{"id": 1, "name": "qgis_editor_apron_taxiway", "description": "..."}],
              "permissions": ["qgis-apron-taxiway:read", "qgis-apron-taxiway:update", ...],
              ...
            }

        PENTING: Apron dan Taxiway itu BUKAN permission tersendiri kayak
        "apron:*"/"taxiway:*". Keduanya cuma baris di tabel ADHPSurfaceArea
        yang dibedain lewat kolom SUBTYPE_CODE (6=Taxiway, 8=Apron). Backend
        punya permission "runway:*" existing yang secara historis menaungi
        ADHPSurfaceArea, TAPI plugin ini SENGAJA GA PAKE itu (scope-nya
        kegedean, nyakup Runway/FATO/TLOF dkk yang di luar cakupan plugin).
        Backend nambahin permission KHUSUS buat plugin ini:
        "qgis-apron-taxiway:read" dan "qgis-apron-taxiway:update". Itu yang
        dicek di `permissions` buat mutusin apakah user boleh liat/edit
        layer Apron/Taxiway (lihat layer_manager.py nanti, sekaligus
        docs/business-rules.md Bagian 4.1 dan repo backend-aim
        docs/aim-pages/qgis-support/qgis-be-business-rules.md).
        """
        url = f"{self.base_url}/me"
        try:
            resp = requests.get(url, headers=self._auth_headers(), timeout=self.timeout)
        except requests.RequestException as exc:
            raise ApiError(f"Request /me gagal: {exc}") from exc

        if resp.status_code != 200:
            raise ApiError(
                f"Request /me gagal ({resp.status_code}): {resp.text}",
                status_code=resp.status_code,
            )

        try:
            return resp.json()
        except ValueError as exc:
            raise ApiError("Response /me bukan JSON yang valid") from exc

    def get_db_credentials(self) -> DbCredentials:
        """
        GET /db-credentials  (Authorization: Bearer <token>)
        -> { "host", "port", "dbname", "schema", "user", "password", "expires_at" }

        Endpoint ini UDAH ADA & jalan di backend (modul internal/dbcredentials/,
        lihat repo backend-aim). Ringkasan alur kerja di sisi server (detail
        lengkap di docs/aim-pages/qgis-support/qgis-be-business-rules.md):
          1. Verifikasi token PASETO (pake AuthMiddleware yang udah ada).
          2. Cek permission qgis-apron-taxiway:update lewat
             middleware.PermissionAuthMiddleware -- kalo ga ada, 403.
          3. Petain ke SATU role PostgreSQL: qgis_writer_apron_taxiway.
             (Mode baca-saja/qgis_reader_apron_taxiway SENGAJA ditunda ke
             iterasi berikutnya, rilis awal cuma ada 1 role.)
             Role Postgres itu cuma boleh nulis/baca ADHPSurfaceArea dengan
             SUBTYPE_CODE 6/8 lewat RLS.
          4. Balikin kredensial role Postgres itu: host, port, dbname, schema,
             user, password, expires_at.

        PENTING soal field `schema`: dikonfirmasi lewat percobaan langsung
        kalo tabel adhp/ADHPSurfaceArea itu TIDAK ada di schema "public" --
        nempatnya di schema yang namanya ngikutin user koneksi database
        backend. WAJIB dipake pas setSchema() di QgsDataSourceUri nanti,
        jangan hardcode/asumsi "public".

        PENTING soal casing identifier SQL: tabel ADHPSurfaceArea dan semua
        kolomnya (SUBTYPE_CODE, ADHP_ID, dst) dibuat TANPA tanda kutip di
        migration backend, jadi PostgreSQL otomatis fold ke huruf kecil
        (tersimpan sebagai adhpsurfacearea, subtype_code, dst). Kalo nanti
        nulis ekspresi setSubsetString()/SQL apa pun di layer_manager.py,
        JANGAN pake tanda kutip di sekitar nama-nama ini -- kalo dikutip,
        Postgres nyari nama persis huruf besar-kecilnya yang ga ada, query
        gagal (dikonfirmasi lewat error nyata pas setup role Postgres).

        Cakupan rilis awal itu per SUBTYPE_CODE (cuma Taxiway=6 & Apron=8),
        bukan per bandara/wilayah, soalnya sistem permission backend emang
        flat/global gitu adanya (ga ada konsep scope per-bandara). Role
        Postgres yang dibalikin WAJIB cuma bisa akses ADHPSurfaceArea (+
        baca adhp), SAMA SEKALI ga boleh akses tabel otorisasi backend
        (users/roles/permissions/dst) walau satu database yang sama.
        """
        url = f"{self.base_url}/db-credentials"
        try:
            resp = requests.get(url, headers=self._auth_headers(), timeout=self.timeout)
        except requests.RequestException as exc:
            raise ApiError(f"Request db-credentials gagal: {exc}") from exc

        if resp.status_code != 200:
            raise ApiError(
                f"Request db-credentials gagal ({resp.status_code}): {resp.text}",
                status_code=resp.status_code,
            )

        try:
            data = resp.json()
            return DbCredentials(
                host=data["host"],
                port=int(data["port"]),
                dbname=data["dbname"],
                schema=data["schema"],
                user=data["user"],
                password=data["password"],
                expires_at=data["expires_at"],
            )
        except (ValueError, KeyError) as exc:
            raise ApiError("Response db-credentials ga lengkap field-nya") from exc
