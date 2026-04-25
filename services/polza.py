import asyncio
import aiohttp
import base64
import logging
import re
import json

from config import POLZA_API_KEY, POLZA_BASE_URL

logger = logging.getLogger(__name__)

NANO_BANANA = "google/gemini-2.5-flash-image"
GPT4O = "openai/gpt-4o"

_session: aiohttp.ClientSession | None = None


async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=180))
    return _session


def _b64(image_bytes: bytes) -> str:
    return base64.standard_b64encode(image_bytes).decode("utf-8")


async def _request(url: str, payload: dict, retries: int = 2) -> tuple[dict, str]:
    """Универсальный POST-запрос. Возвращает (parsed_json, raw_text)."""
    headers = {
        "Authorization": f"Bearer {POLZA_API_KEY}",
        "Content-Type": "application/json",
    }
    session = await _get_session()
    for attempt in range(retries + 1):
        try:
            async with session.post(url, json=payload, headers=headers) as resp:
                raw = await resp.text()
                if resp.status == 200:
                    return json.loads(raw), raw
                elif resp.status >= 500 and attempt < retries:
                    await asyncio.sleep(5)
                    continue
                else:
                    raise PolzaAPIError(f"HTTP {resp.status}: {raw[:300]}")
        except aiohttp.ClientError as e:
            if attempt < retries:
                await asyncio.sleep(5)
            else:
                raise PolzaAPIError(str(e))
    raise PolzaAPIError("Max retries exceeded")


async def _download_url(url: str) -> bytes:
    """Скачивает файл по URL и возвращает байты."""
    session = await _get_session()
    async with session.get(url) as resp:
        if resp.status != 200:
            raise PolzaAPIError(f"Failed to download image: HTTP {resp.status}")
        return await resp.read()


async def _chat(payload: dict) -> dict:
    """Запрос к /chat/completions."""
    url = f"{POLZA_BASE_URL}/chat/completions"
    data, _ = await _request(url, payload)
    return data


async def _media(payload: dict) -> tuple[dict, str]:
    """Запрос к /media."""
    url = f"{POLZA_BASE_URL}/media"
    return await _request(url, payload)


async def _extract_image_from_media(data: dict, raw: str) -> bytes | None:
    """
    Извлекает изображение из ответа /api/v1/media.

    Реальная структура ответа polza.ai:
    {
      "data": [{"url": "https://s3.polza.ai/..."}]
    }
    """
    try:
        # 1. data[].url — картинка на S3 (основной формат polza.ai)
        top_data = data.get("data")
        if isinstance(top_data, list) and top_data:
            item = top_data[0]
            if isinstance(item, dict):
                url_val = item.get("url", "")
                if url_val.startswith("http"):
                    logger.info(f"Downloading image from S3: {url_val}")
                    return await _download_url(url_val)

                b64 = item.get("b64_json") or item.get("base64") or item.get("data")
                if b64:
                    if isinstance(b64, str) and b64.startswith("data:"):
                        _, b64 = b64.split(",", 1)
                    return base64.b64decode(b64)

        # 2. output.images[] — альтернативный формат
        output = data.get("output") or {}
        images = output.get("images") or output.get("image") or []
        if isinstance(images, dict):
            images = [images]

        for img in images:
            if not isinstance(img, dict):
                continue
            img_data = img.get("data", "")
            img_type = img.get("type", "")

            if img_type == "base64" and img_data:
                return base64.b64decode(img_data)

            url_val = img.get("url", "")
            if url_val.startswith("http"):
                return await _download_url(url_val)

            if isinstance(img_data, str) and img_data.startswith("data:"):
                _, b64 = img_data.split(",", 1)
                return base64.b64decode(b64)

        # 3. Поиск data URI в сыром ответе
        match = re.search(r'data:image/[^;]+;base64,([A-Za-z0-9+/=\n\r ]{100,})', raw)
        if match:
            logger.info("Found image via data URI in raw response")
            return base64.b64decode(re.sub(r'\s', '', match.group(1)))

        # 4. Поиск bare base64 в известных JSON-полях
        for field in ("b64_json", "base64", "image_data"):
            match = re.search(r'"' + field + r'"\s*:\s*"([A-Za-z0-9+/=]{200,})"', raw)
            if match:
                logger.info(f"Found image in raw JSON field '{field}'")
                try:
                    return base64.b64decode(match.group(1))
                except Exception:
                    pass

        logger.error(
            f"[media] Could not extract image.\n"
            f"data keys: {list(data.keys())}\n"
            f"raw (first 800): {raw[:800]}"
        )

    except PolzaAPIError:
        raise
    except Exception as e:
        logger.error(f"[media] Exception extracting image: {e}\nRaw: {raw[:300]}")

    return None


async def tryon(user_photo_bytes: bytes, item_photos_bytes: list,
                quality: str = "high", season: str = None, sizes: str = None) -> bytes:
    """Примерка одежды через /api/v1/media (Nano Banana)."""
    season_text = f" Adapt the outfit for season: {_season_en(season)}." if season else ""
    sizes_text = (
        f" The user provided size information: \"{sizes}\". "
        "Use this to render how the clothing would realistically fit the person "
        "(e.g. tight, loose, oversized) while still preserving their true body proportions."
    ) if sizes else ""
    n = len(item_photos_bytes)

    if n == 1:
        prompt = (
            "Virtual try-on for a fashion retailer product page. "
            "Image 1 = the model. Image 2 = the product (garment to be worn). "
            "TASK: produce one photorealistic image of the model from Image 1 wearing the exact product from Image 2, "
            "as if this were an official product-on-model photo for an e-commerce listing. "
            "The viewer must be able to recognise Image 2 as the same garment in the result — "
            "if they place Image 2 and the result side by side, every detail must match. "
            ""
            "GARMENT — treat Image 2 as a pixel-accurate texture reference, NOT as inspiration. "
            "Reproduce with zero artistic deviation: "
            "COLOUR: match every colour zone exactly — hue, saturation and brightness must not shift by any amount. "
            "SEAMS & CONSTRUCTION: reproduce all visible seams, topstitching, overlock edges, darts and construction lines. "
            "CLOSURES: every button (shape, colour, size, count, exact position), zip (type, length, pull hardware), snap or tie — replicate precisely. "
            "PRINT / GRAPHIC / LOGO / TEXT / EMBROIDERY: reproduce scale, colour, position and orientation exactly; do not redraw, stylise or simplify. "
            "FABRIC: match the surface appearance — matte/shiny, rough/smooth, knit structure, weave pattern, drape weight. "
            "SILHOUETTE & FIT: oversized / boxy / relaxed / regular / slim / tailored — replicate exactly; do not normalise to a generic fit. "
            "SLEEVES: match length (sleeveless/cap/short/elbow/3-quarter/long), width, taper and cuff style exactly. "
            "If Image 2 is a flat-lay or hanger shot, reconstruct the natural worn sleeve shape from the cuff area and garment proportions — do not borrow sleeve shape from any other source. "
            "NECKLINE & COLLAR: exact shape, height, lapel type or collar style. "
            "HEM: exact length (crop/waist/hip/thigh/knee/midi/maxi) and shape (straight/curved/asymmetric/split). "
            "LABELS, PATCHES, HARDWARE: any visible labels, tags, patches or metal hardware must appear in the result. "
            ""
            "MODEL — preserve from Image 1 without any change: "
            "face, expression, skin tone, hair, body proportions, natural pose, background and lighting. "
            ""
            "ABSOLUTE CONSTRAINTS: "
            "1. The outfit in the final image consists solely of the product from Image 2. No other garments are visible. "
            "2. Do not invent, stylise, average or hallucinate any garment detail — Image 2 is the only authority. "
            "3. Do not alter the model's body shape — the garment adapts to the model, not vice versa. "
            f"4. Result must be photorealistic and suitable for an e-commerce product page.{season_text}{sizes_text} "
            "Output: one image."
        )
    else:
        prompt = (
            "Virtual try-on for a fashion retailer product page. "
            "Image 1 = the model. "
            f"Images 2 to {n+1} = the products (garments that together form the complete outfit). "
            "TASK: produce one photorealistic image of the model from Image 1 wearing all products from Images 2 onwards, "
            "as if this were an official product-on-model photo for an e-commerce listing. "
            "The viewer must be able to recognise each source garment image in the result — "
            "if they place each garment image beside the result, every detail must match. "
            ""
            "EACH GARMENT — treat its source image as a pixel-accurate texture reference, NOT as inspiration. "
            "For every garment reproduce with zero artistic deviation: "
            "COLOUR: exact hue, saturation and brightness — no shift. "
            "SEAMS & CONSTRUCTION: all visible seams, topstitching, overlock edges, darts and construction lines. "
            "CLOSURES: every button, zip, snap or tie — shape, colour, size, count and position replicated precisely. "
            "PRINT / GRAPHIC / LOGO / TEXT / EMBROIDERY: scale, colour, position and orientation exact; do not redraw or stylise. "
            "FABRIC: surface appearance, drape weight, sheen and texture. "
            "SILHOUETTE & FIT: exact — do not normalise. "
            "SLEEVES: exact length, width, taper and cuff style. If source is a flat-lay or hanger, infer worn sleeve shape from cuff area. "
            "NECKLINE & COLLAR: exact. "
            "HEM: exact length and shape. "
            "LABELS, PATCHES, HARDWARE: replicate any visible details. "
            ""
            "LAYERING: assemble into a coherent outfit respecting natural layering order (e.g. shirt under jacket, trousers under skirt hem). "
            ""
            "MODEL — preserve from Image 1 without any change: "
            "face, expression, skin tone, hair, body proportions, natural pose, background and lighting. "
            ""
            "ABSOLUTE CONSTRAINTS: "
            "1. The outfit consists solely of the products from the garment images. No other garments are visible. "
            "2. Do not invent, stylise, average or hallucinate any garment detail — each source image is the only authority for that garment. "
            "3. Do not alter the model's body shape — each garment adapts to the model, not vice versa. "
            f"4. Result must be photorealistic and suitable for an e-commerce product page.{season_text}{sizes_text} "
            "Output: one image."
        )

    all_images = [user_photo_bytes] + list(item_photos_bytes)
    images_payload = [
        {"type": "base64", "data": _b64(img_bytes), "media_type": "image/jpeg"}
        for img_bytes in all_images
    ]

    payload = {
        "model": NANO_BANANA,
        "input": {
            "prompt": prompt,
            "images": images_payload,
            "aspect_ratio": "3:4",
            "output_format": "jpeg",
        },
    }

    data, raw = await _media(payload)

    if data.get("status") == "failed":
        err = data.get("error", {})
        code = err.get("code", "")
        if code == "FORBIDDEN":
            raise PolzaAPIError("Фото заблокировано фильтрами безопасности. Попробуй другое фото.")
        raise PolzaAPIError(f"Генерация не удалась: {err.get('message', 'неизвестная ошибка')}")

    image_bytes = await _extract_image_from_media(data, raw)

    if not image_bytes:
        raise PolzaAPIError(
            f"Не удалось получить изображение от Нано Банано.\n"
            f"data keys: {list(data.keys())}\n"
            f"raw (500): {raw[:500]}"
        )

    return image_bytes


async def style_advice(outfit_description: str) -> str:
    payload = {
        "model": GPT4O,
        "messages": [
            {"role": "system", "content": "Ты профессиональный стилист. Отвечай на русском."},
            {"role": "user", "content": (
                f"Дай совет по стилю: {outfit_description}. "
                "Оцени сочетаемость цветов, что добавить или убрать, предложи аксессуары. До 150 слов."
            )}
        ],
        "max_tokens": 400,
    }
    result = await _chat(payload)
    return result["choices"][0]["message"]["content"]


async def similar_items(item_description: str) -> list:
    payload = {
        "model": GPT4O,
        "messages": [
            {"role": "system", "content": "Отвечай ТОЛЬКО валидным JSON без markdown."},
            {"role": "user", "content": (
                f"Предложи 5 товаров похожих на: {item_description}. "
                'JSON массив: [{"name": "название", "url": "https://www.wildberries.ru/catalog/0/search.aspx?search=запрос"}]'
            )}
        ],
        "max_tokens": 600,
    }
    result = await _chat(payload)
    text = result["choices"][0]["message"]["content"]
    try:
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception:
        pass
    return []


def _season_en(season: str) -> str:
    return {"spring": "spring", "summer": "summer", "autumn": "autumn", "winter": "winter"}.get(season or "", "")


class PolzaAPIError(Exception):
    pass


polza_client = type("PolzaClient", (), {
    "tryon": staticmethod(tryon),
    "style_advice": staticmethod(style_advice),
    "similar_items": staticmethod(similar_items),
})()
