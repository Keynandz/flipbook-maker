# Flipbook PDF Viewer API

Sebuah API sederhana berbasis FastAPI untuk mengunggah file PDF dan mengubahnya menjadi tampilan flipbook interaktif berbasis HTML & JavaScript.

## Fitur

- Unggah file PDF via API
- Konversi halaman PDF menjadi gambar PNG
- Simpan file ke penyimpanan S3-compatible (misal: MinIO)
- Tampilkan flipbook interaktif berbasis HTML & JavaScript

## Teknologi

- FastAPI
- Uvicorn
- pdf2image
- Pillow
- Boto3 (untuk interaksi dengan S3/MinIO)
- Static HTML/JS Flipbook viewer
