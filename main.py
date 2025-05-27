from fastapi import FastAPI, File, UploadFile, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from pdf2image import convert_from_bytes
import boto3
import os
import uuid
from io import BytesIO
from dotenv import load_dotenv
from datetime import datetime
from typing import List, Dict
import re

load_dotenv()

app = FastAPI()

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9001")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "pdf-images")
MINIO_PUBLIC_URL = os.getenv("MINIO_PUBLIC_URL", f"http://{MINIO_ENDPOINT}/{MINIO_BUCKET}")

s3 = boto3.client(
    's3',
    endpoint_url=f"http://{MINIO_ENDPOINT}",
    aws_access_key_id=MINIO_ACCESS_KEY,
    aws_secret_access_key=MINIO_SECRET_KEY
)

flipbooks_db: Dict[str, Dict] = {}

try:
    s3.head_bucket(Bucket=MINIO_BUCKET)
except:
    s3.create_bucket(Bucket=MINIO_BUCKET)


def extract_youtube_id(url: str) -> str:
    regex = r"(?:v=|\/)([0-9A-Za-z_-]{11}).*"
    match = re.search(regex, url)
    if match:
        return match.group(1)
    elif len(url) >= 11:
        return url[-11:]
    return ""

def max_page(image_urls: List[str], video_embeds: List[Dict] = []) -> int:
    return len(image_urls) + len(video_embeds) + 1


def generate_flipbook_html(image_urls: List[str], flipbook_id: str, video_embeds: List[Dict] = []) -> str:
    pages = []

    def page_div(page_num, content_html, even_or_odd):
        return f"""
        <div class="page {even_or_odd}" id="page-{page_num}">
            <div class="page-content">
                {content_html}
            </div>
        </div>
        """

    def image_page(url, page_num):
        even_or_odd = "even" if page_num % 2 != 0 else "odd"
        return page_div(page_num, f'<img src="{url}" style="max-width: 100%; height: auto;" />', even_or_odd)

    def video_page(page_num, video_id):
        even_or_odd = "even" if page_num % 2 != 0 else "odd"
        iframe_html = f"""
        <iframe width="560" height="315"
            src="https://www.youtube.com/embed/{video_id}"
            frameborder="0" allowfullscreen>
        </iframe>
        """
        return page_div(page_num, iframe_html, even_or_odd)

    # Tambahkan halaman cover (halaman pertama)
    pages.append(image_page(image_urls[0], 1))

    all_pages = []
    video_embeds = video_embeds or []
    video_page_map = {v["page"]: v["video_id"] for v in video_embeds}

    idx = 2
    for url in image_urls[1:]:
        if idx in video_page_map:
            all_pages.append(video_page(idx, video_page_map[idx]))
            idx += 1
        all_pages.append(image_page(url, idx))
        idx += 1

    # Tambahkan video yang ditempatkan di halaman lebih besar dari halaman akhir
    for v in video_embeds:
        if v["page"] >= idx:
            all_pages.append(video_page(v["page"], v["video_id"]))

    pages.extend(all_pages)

    # Sortir dan tambahkan halaman kosong jika ganjil
    def get_page_num(page_html):
        m = re.search(r'id="page-(\d+)"', page_html)
        return int(m.group(1)) if m else 0

    pages = sorted(pages, key=get_page_num)

    total_pages = len(pages)
    if total_pages % 2 != 0:
        pages.append(page_div(total_pages + 1, "", "odd" if (total_pages + 1) % 2 == 0 else "even"))
        total_pages += 1

    pages_html = "\n".join(pages)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>PDF Flipbook - {flipbook_id}</title>
    <link rel="stylesheet" href="/static/style.css">
    <style>
        #book {{
            width: 800px;
            height: 600px;
            margin: 20px auto;
        }}
        .page-content {{
            width: 100%;
            height: 100%;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
            box-sizing: border-box;
        }}
        .page-content img {{
            max-height: 100%;
            max-width: 100%;
            object-fit: contain;
        }}
    </style>
</head>
<body>
    <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
    <script src="/static/script.js"></script>

    <div id="book">
        {pages_html}
    </div>

    <script>
        $(function() {{
            $('#book').turn({{
                width: 800,
                height: 600,
                autoCenter: true,
                display: 'double',
                acceleration: true,
                elevation: 50,
                gradients: true,
            }});
        }});
    </script>
</body>
</html>
"""
    return html


@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Hanya file PDF yang diizinkan")

    content = await file.read()

    try:
        images = convert_from_bytes(content)
        uploaded_files = []
        image_urls = []

        filename_no_ext = os.path.splitext(file.filename)[0]
        now = datetime.now()
        time_str = now.strftime("%Y%m%d%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        storage_path = f"pdf/{filename_no_ext}_{time_str}_{unique_id}"

        for idx, img in enumerate(images):
            img_byte_arr = BytesIO()
            img.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)

            minio_path = f"{storage_path}/page_{idx + 1}.png"
            s3.upload_fileobj(img_byte_arr, MINIO_BUCKET, minio_path, ExtraArgs={"ContentType": "image/png"})
            image_urls.append(f"{MINIO_PUBLIC_URL}/{minio_path}")

        flipbook_id = f"{filename_no_ext}_{time_str}_{unique_id}"
        flipbooks_db[flipbook_id] = {
            "id": flipbook_id,
            "created_at": now.isoformat(),
            "original_filename": file.filename,
            "image_urls": image_urls,
            "video_embeds": []  # simpan banyak video di sini
        }

        return {
            "message": "PDF berhasil dikonversi dan diunggah ke MinIO",
            "flipbook_id": flipbook_id,
            "flipbook_url": f"/flipbook/{flipbook_id}"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/flipbook/{flipbook_id}")
async def get_flipbook(flipbook_id: str, request: Request):
    if flipbook_id not in flipbooks_db:
        raise HTTPException(status_code=404, detail="Flipbook tidak ditemukan")

    flipbook = flipbooks_db[flipbook_id]
    html = generate_flipbook_html(flipbook["image_urls"], flipbook_id, flipbook.get("video_embeds", []))
    return HTMLResponse(content=html, status_code=200)


@app.post("/flipbook/{flipbook_id}/add_video_embed")
async def add_video_embed(flipbook_id: str, video_url: str = Form(...), page: int = Form(...)):
    if flipbook_id not in flipbooks_db:
        raise HTTPException(status_code=404, detail="Flipbook tidak ditemukan")

    if page <= 1:
        raise HTTPException(status_code=400, detail="Video tidak boleh disisipkan di halaman cover (page 1)")

    flipbook = flipbooks_db[flipbook_id]
    maxPage = max_page(flipbook["image_urls"], flipbook.get("video_embeds", []))
    if page > maxPage:
        raise HTTPException(status_code=400, detail=f"Halaman tidak valid. Maksimal halaman adalah {maxPage}")

    video_id = extract_youtube_id(video_url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Video URL tidak valid")

    video_data = {"page": page, "video_id": video_id}
    flipbooks_db[flipbook_id]["video_embeds"].append(video_data)

    return {
        "message": f"Video berhasil ditambahkan ke halaman {page}",
        "video_id": video_id,
        "flipbook_id": flipbook_id
    }

@app.get("/flipbook/{flipbook_id}/view")
async def view_flipbook_with_embed(flipbook_id: str):
    """
    Tampilkan flipbook dengan embed video jika ada
    """
    if flipbook_id not in flipbooks_db:
        raise HTTPException(status_code=404, detail="Flipbook tidak ditemukan")

    flipbook = flipbooks_db[flipbook_id]

    video_embed = flipbook.get("video_embed")
    html = generate_flipbook_html(flipbook["image_urls"], flipbook_id, video_embed)

    return HTMLResponse(content=html)


# Static files for CSS and JS
from fastapi.staticfiles import StaticFiles

app.mount("/static", StaticFiles(directory="static"), name="static")

# Make sure you have a 'static' folder containing:
# style.css and script.js (turn.js library and your custom JS)
