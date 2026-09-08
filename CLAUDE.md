# CLAUDE.md — Panduan Proyek qgis-aim

## Konvensi Bahasa (WAJIB)

- **File dokumentasi** (`docs/*.md`, `README.md`, dsb.) ditulis dalam **Bahasa Indonesia formal**.
- **Comments/docstring di dalam code** (Python, dsb.) ditulis dalam **Bahasa Indonesia santai/informal**, gaya komunikasi antar-developer. Buat selengkap mungkin: sertakan deskripsi singkat di header file, serta di setiap procedure/function (bukan cuma komentar inline sesekali).

## Tentang Proyek

Plugin QGIS Python bernama **AIM Editor** (folder `aim_editor/`) untuk mengedit geometri data AIS/ICAO kebandarudaraan di PostGIS: parent = tabel `adhp` (PK `gfid`, VARCHAR(38)), child rilis awal = tabel `ADHPSurfaceArea` (PK `GFID`, FK `ADHP_ID`), dibatasi ke `SUBTYPE_CODE` 6 (Taxiway) dan 8 (Apron) saja. Otorisasi dijembatani lewat REST API existing (`backend-aim`, Go/Gin) yang memakai token PASETO.

Lihat [docs/business-rules.md](docs/business-rules.md) untuk aturan bisnis lengkap, [docs/implementation-plan.md](docs/implementation-plan.md) untuk rencana implementasi, dan [docs/dev-log.md](docs/dev-log.md) untuk riwayat pekerjaan (update setiap sesi kerja signifikan, format ringkas ala `aim-dev-log-summary.md` di backend-aim/web-aim).

## Keputusan Arsitektur Kunci (jangan diubah tanpa konfirmasi user)

- Login plugin ke REST API -> dapat PASETO access token (opaque, tidak di-decode plugin) -> panggil `GET /db-credentials` (endpoint baru, perlu dibuat di backend) -> dapat kredensial PostgreSQL **per kelompok hak akses** (bukan shared account, bukan per user individu, bukan role pemilik skema).
- Otorisasi plugin pakai **permission & role aplikasi baru yang khusus** (`qgis-apron-taxiway:read`/`update`, role `qgis_editor_apron_taxiway`/`qgis_viewer_apron_taxiway`) — bukan menumpang pada `runway:*`/`admin_aerodrome`/`editor_aerodrome` existing yang cakupannya lebih luas.
- Kredensial DB di sisi klien **wajib** disimpan lewat `QgsAuthManager`/`QgsAuthMethodConfig` (terenkripsi di `qgis-auth.db`), layer dibuka pakai `setAuthConfigId`, **bukan** `setUsername`/`setPassword` langsung.
- Editing geometri native QGIS↔PostGIS (bukan lewat REST API) — supaya snapping/undo/redo/form atribut tetap standar QGIS. Proteksi sesungguhnya ada di level DB (grant per role + RLS berbasis `SUBTYPE_CODE`), bukan di plugin.
- Mitigasi wajib: Row-Level Security per `SUBTYPE_CODE` (bukan per bandara/wilayah — sistem permission backend flat/global), grant Postgres role plugin **hanya** ke `ADHPSurfaceArea`+`adhp` (sama sekali tidak ke tabel otorisasi backend walau satu database yang sama), kolom audit `last_edited_user`/`last_edited_date` (sudah ada di skema tapi wajib diisi plugin sendiri — tidak ada trigger), pembatasan jaringan (VPN/internal only).
- Alur UX: login dialog custom -> fetch `/me` (permissions) & kredensial -> load layer Apron/Taxiway sesuai permission (Browser Panel disembunyikan) -> search parent `adhp` (ICAO/IATA/nama) -> layer difilter `setSubsetString()` berdasar `ADHP_ID` + `SUBTYPE_CODE` -> canvas zoom ke lokasi bandara -> edit native -> `ADHP_ID`/`SUBTYPE_CODE`/kolom audit terisi otomatis via `QgsDefaultValueDefinition` (read-only di form) -> commit native ke PostGIS.
- Cakupan rilis awal **sengaja sempit** (hanya Apron+Taxiway) dan dirancang untuk ditambah entitas/subtipe lain **satu per satu** di iterasi mendatang — bukan mendukung seluruh skema AIS/ICAO sekaligus.

## Dokumen Terkait di Repo Backend (`backend-aim`)

Pekerjaan sisi backend (permission/role baru, endpoint `/db-credentials`, grant PostgreSQL, RLS) didokumentasikan **terpisah** di repo `backend-aim` (bukan di sini), mengikuti konvensi dokumentasi modul mereka sendiri:
- `backend-aim/docs/aim-pages/qgis-support/qgis-be-business-rules.md`
- `backend-aim/docs/aim-pages/qgis-support/qgis-be-implementation-plan.md`

## Catatan Penting

Skema data GIS (`adhp`/`ADHPSurfaceArea`) dan skema rights/roles REST API backend **sudah dikonfirmasi lewat riset langsung ke repo `backend-aim`** — bukan lagi asumsi/placeholder. Jangan tanya user ulang soal skema dasar ini; baca `docs/business-rules.md` Bagian 1 dan 9 untuk detail lengkap. Kalau ada perubahan skema di masa depan (backend masih aktif dikembangkan), verifikasi ulang lewat riset ke repo backend, bukan asumsi dari memori sesi lama.
