"""Image OCR helper - automatically extracts text from QQ images."""
import html, re, httpx, tempfile, os, subprocess
from io import BytesIO
from PIL import Image

def _ensure_png(img_data: bytes) -> bytes:
    """Convert any image format to PNG bytes. Handles GIF (first frame), WebP, etc."""
    try:
        img = Image.open(BytesIO(img_data))
        if getattr(img, "is_animated", False):
            img.seek(0)
            img = img.convert("RGBA") if img.mode == "P" else img
        # Composite onto white background for RGBA/PA to avoid black transparency
        if img.mode in ("RGBA", "PA"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            mask = img.split()[-1] if img.mode == "RGBA" else None
            bg.paste(img, mask=mask)
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as e:
        print(f"[ocr_helper] Image conversion failed: {e}, falling back to raw")
        return img_data


async def ocr_image_from_url(url: str) -> str:
    """Download a single QQ image URL and run Tesseract OCR. Returns extracted text or empty string."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://multimedia.nt.qq.com.cn/",
    }
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as cli:
            resp = await cli.get(url, headers=headers)
            if resp.status_code != 200:
                print(f'[ocr_helper] HTTP {resp.status_code} for {url[:100]}')
                return ''
            img_data = resp.content
            ct = resp.headers.get('content-type', '')
            print(f'[ocr_helper] Downloaded {len(img_data)} bytes, type={ct}')

        img_data = _ensure_png(img_data)

        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            f.write(img_data)
            tmp_path = f.name

        out_path = tmp_path + '_ocr'
        result = subprocess.run(
            ['tesseract', tmp_path, out_path, '-l', 'chi_sim+eng', '--oem', '1'],
            capture_output=True, text=True, timeout=20
        )
        os.unlink(tmp_path)

        if result.returncode == 0 and os.path.exists(out_path + '.txt'):
            with open(out_path + '.txt', 'r', encoding='utf-8') as f:
                text = f.read().strip()
            os.unlink(out_path + '.txt')
            if text:
                print(f'[ocr_helper] OCR extracted {len(text)} chars')
                return text[:1500]
            else:
                print(f'[ocr_helper] OCR returned empty text')
        else:
            print(f'[ocr_helper] tesseract failed: rc={result.returncode} stderr={result.stderr[:100]}')
        return ''
    except Exception as e:
        print(f'[ocr_helper] Error: {e}')
        return ''


async def ocr_images_from_message(raw_msg: str) -> str:
    """Extract and OCR all images from a raw QQ message. Returns OCR text or empty string."""
    urls = []
    for m in re.finditer(r'\[(?:CQ:)?image,[^\]]*url=(https?://[^,\]]+)', raw_msg):
        url = html.unescape(m.group(1))
        if url:
            urls.append(url)

    if not urls:
        return ""

    results = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://multimedia.nt.qq.com.cn/",
    }

    for url in urls[:3]:
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as cli:
                resp = await cli.get(url, headers=headers)
                if resp.status_code != 200:
                    print(f"[ocr_helper] HTTP {resp.status_code} for {url[:100]}")
                    continue
                img_data = resp.content
                ct = resp.headers.get("content-type", "")
                print(f"[ocr_helper] Downloaded {len(img_data)} bytes, type={ct}")

            # Convert GIF/WebP/etc to PNG for tesseract
            img_data = _ensure_png(img_data)

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                f.write(img_data)
                tmp_path = f.name

            out_path = tmp_path + "_ocr"
            result = subprocess.run(
                ["tesseract", tmp_path, out_path, "-l", "chi_sim+eng", "--oem", "1"],
                capture_output=True, text=True, timeout=20
            )
            os.unlink(tmp_path)

            if result.returncode == 0 and os.path.exists(out_path + ".txt"):
                with open(out_path + ".txt", "r", encoding="utf-8") as f:
                    text = f.read().strip()
                os.unlink(out_path + ".txt")
                if text:
                    results.append(text[:1500])
                    print(f"[ocr_helper] OCR extracted {len(text)} chars")
                else:
                    print(f"[ocr_helper] OCR returned empty text")
            else:
                print(f"[ocr_helper] tesseract failed: rc={result.returncode} stderr={result.stderr[:100]}")
        except Exception as e:
            print(f"[ocr_helper] Error: {e}")

    if results:
        return chr(92)+"n---"+chr(92)+"n".join(results)
    return ""
