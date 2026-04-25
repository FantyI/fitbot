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


async def _describe_garment(item_bytes: bytes) -> tuple[str, str]:
    """
    Analyse garment image with GPT-4o.
    Returns (coverage, description) where coverage is 'upper-body' | 'lower-body' | 'full-body'.
    """
    b64_img = _b64(item_bytes)
    payload = {
        "model": GPT4O,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"},
                    },
                    {
                        "type": "text",
                        "text": (
                            "You are a garment analyst for a virtual try-on system. "
                            "Fill in the structured template below for this clothing item. "
                            "Rules: be confident and precise — zero hedging words (no 'appears', 'seems', 'possibly', 'likely'). "
                            "Describe ONLY the garment design — ignore photography (lighting, background, hanger, mannequin, cast shadows). "
                            "Use proportional sizes (% of garment width or length) not centimetres.\n\n"
                            "COVERAGE: [upper-body | lower-body | full-body]\n"
                            "SILHOUETTE: [oversized-boxy | relaxed | regular | slim | fitted | tailored | A-line | etc.]\n"
                            "COLOUR_ZONES: [each zone with exact colour, e.g. 'body: off-white, sleeves: same, collar: dark navy']\n"
                            "LOGO_GRAPHIC: [shape, colours, any text, size as % of chest width, position as % from garment top and from left/right edge — or NONE]\n"
                            "EMBROIDERY_PATCHES: [details — or NONE]\n"
                            "SEAMS: [locations, single or double topstitch, thread colour]\n"
                            "NECKLINE: [exact type: crew-neck / V-neck / scoop / button-down / mandarin / polo / hood / turtleneck / etc., and depth]\n"
                            "SLEEVES:\n"
                            "  SLEEVE_SHOULDER_JOIN: [set-in (standard armhole seam) | raglan (diagonal seam from underarm to neck) | drop-shoulder (seam falls below shoulder point) | kimono/dolman (no seam, cut as one with body)]\n"
                            "  SLEEVE_LENGTH: [sleeveless | cap | short(above-elbow) | elbow | 3-quarter | long | extra-long(past wrist)]\n"
                            "  SLEEVE_WIDTH_SHOULDER: [narrow | regular | wide | very-wide] as % of total shoulder width\n"
                            "  SLEEVE_WIDTH_CUFF: [narrow | regular | wide] — state if same as shoulder or different\n"
                            "  SLEEVE_TAPER: [straight (parallel) | tapers-to-narrow-cuff | tapers-significantly | widens-toward-cuff | balloon]\n"
                            "  SLEEVE_CUFF: [style: ribbed-band/plain-hem/button-placket/elasticated/raw/turned-up; colour: same-as-sleeve/contrasting; width: narrow/medium/wide]\n"
                            "  SLEEVE_DESIGN: [any stripes, colour-blocks, patches, prints, seam lines or other design elements on sleeves — or NONE]\n"
                            "CLOSURES: [type, count, colour, size, positions — or NONE]\n"
                            "HEM: [length: crop/waist/hip/thigh/knee/midi/maxi; shape: straight/curved/asymmetric/split; finishing]\n"
                            "POCKETS: [count, type, positions — or NONE]\n"
                            "FABRIC: [texture: smooth/rough/ribbed-knit/cable-knit/woven/denim; weight: light/medium/heavy; sheen: matte/slight/shiny; drape: stiff/structured/fluid]\n"
                            "TRANSPARENCY: [opaque | semi-transparent | transparent]\n"
                            "HARDWARE_LABELS: [metal hardware, woven labels, printed tags, reflective elements — or NONE]\n"
                            "OTHER: [any unique feature not covered above — or NONE]\n"
                        ),
                    },
                ],
            }
        ],
        "max_tokens": 700,
    }
    try:
        result = await _chat(payload)
        description = result["choices"][0]["message"]["content"].strip()

        coverage = "upper-body"
        for line in description.split("\n")[:6]:
            if "COVERAGE:" in line.upper():
                val = line.split(":", 1)[1].strip().lower()
                if "lower" in val:
                    coverage = "lower-body"
                elif "full" in val:
                    coverage = "full-body"
                break

        return coverage, description
    except Exception as e:
        logger.warning(f"Garment description failed: {e}")
        return "upper-body", ""


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

    # Step 1 — Pre-analyse garment(s) with GPT-4o.
    # Structured key:value description gives Gemini a second channel for fine
    # details (logo position, seam type, colours) that generative models hallucinate.
    # Also extracts coverage type so we know which body zone to replace.
    if n == 1:
        results = [await _describe_garment(item_photos_bytes[0])]
    else:
        results = list(await asyncio.gather(
            *[_describe_garment(b) for b in item_photos_bytes]
        ))
    coverages = [r[0] for r in results]
    descs = [r[1] for r in results]

    def _checklist_block(desc: str, label: str) -> str:
        if not desc:
            return ""
        return (
            f"DETAIL CHECKLIST FOR {label} "
            f"(mandatory — every field below must be reflected in the result exactly as stated): "
            f"{desc} "
        )

    def _body_zone_rule(coverage: str) -> str:
        if coverage == "lower-body":
            return (
                "BODY ZONE: Image 2 is a lower-body garment. "
                "Replace ONLY the lower-body clothing of the model. "
                "Preserve the exact upper-body clothing (top, shirt, jacket, etc.) from Image 1 unchanged. "
            )
        if coverage == "full-body":
            return (
                "BODY ZONE: Image 2 is a full-body garment (dress, jumpsuit, coat, etc.). "
                "Replace the model's entire visible clothing with this garment. "
            )
        return (
            "BODY ZONE: Image 2 is an upper-body garment. "
            "Replace ONLY the upper-body clothing of the model. "
            "Preserve the exact lower-body clothing (trousers, skirt, shorts, etc.) and footwear from Image 1 unchanged. "
        )

    if n == 1:
        checklist = _checklist_block(descs[0], "THE GARMENT (Image 2)")
        body_zone = _body_zone_rule(coverages[0])
        prompt = (
            "I have two photos. "
            "Photo 1: a person — this is the ONLY person who must appear in my output. "
            "Photo 2: a clothing item — this is the ONLY source for the garment design. "
            "Photo 2 may show the clothing on a flat surface, on a hanger, on a mannequin, or on a different person. "
            "That other person in Photo 2 (if any) does NOT appear in the output. Only the garment design from Photo 2 is used. "
            ""
            "Task: create a new realistic photo of the person from Photo 1 wearing the clothing from Photo 2. "
            ""
            f"{body_zone}"
            ""
            "Requirements for the output: "
            "— The face, hair, skin tone and body of the person from Photo 1 are preserved exactly. "
            "— The clothing design from Photo 2 is reproduced exactly: colours, silhouette, logo, seams, sleeves, collar, hem, fabric texture. "
            "— Sleeves match Photo 2: length, width, shoulder join type, cuff. If Photo 2 is a flat-lay, reconstruct worn sleeve shape from proportions. "
            "— The garment wraps naturally around the body with realistic folds and draping — not pasted on top. "
            "— Lighting on the garment is consistent with the scene in Photo 1. "
            f"{checklist}"
            f"{season_text}{sizes_text}"
            "Output: one photorealistic image."
        )
    else:
        # Outfit: user is intentionally building a full look — replace all clothing
        checklists = "".join(
            _checklist_block(desc, f"GARMENT {i+1} (Image {i+2})")
            for i, desc in enumerate(descs)
        )
        prompt = (
            f"I have {n+1} photos. "
            "Photo 1: a person — this is the ONLY person who must appear in my output. "
            f"Photos 2 to {n+1}: clothing items — these are the ONLY sources for garment designs. "
            "Each clothing photo may show the item on a flat surface, hanger, mannequin, or a different person. "
            "Any other person in those photos does NOT appear in the output. Only the garment designs are used. "
            ""
            f"Task: create a new realistic photo of the person from Photo 1 wearing all the clothing from Photos 2 to {n+1}. "
            ""
            "Requirements for the output: "
            "— The face, hair, skin tone and body of the person from Photo 1 are preserved exactly. "
            "— Each clothing item's design is reproduced exactly: colours, silhouette, logo, seams, sleeves, collar, hem, fabric texture. "
            "— Sleeves match their source photo: length, width, shoulder join type, cuff. Flat-lay sleeves → reconstruct worn shape. "
            "— All garments wrap naturally around the body with realistic folds and draping. "
            "— Layering is natural (e.g. shirt under jacket). "
            "— Lighting on all garments is consistent with the scene in Photo 1. "
            f"{checklists}"
            f"{season_text}{sizes_text}"
            "Output: one photorealistic image."
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

    input_set = {user_photo_bytes} | set(item_photos_bytes)

    for attempt in range(2):
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

        if image_bytes in input_set:
            if attempt == 0:
                logger.warning("Passthrough detected, retrying...")
                continue
            raise PolzaAPIError("Модель вернула исходное изображение без изменений. Попробуй снова.")

        return image_bytes

    raise PolzaAPIError("Не удалось получить результат после повторной попытки.")


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
