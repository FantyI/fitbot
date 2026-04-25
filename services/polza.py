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
            "Virtual try-on. "
            "Image 1 = the person whose face and body must appear in the final result. "
            "Image 2 = the garment design source ONLY — whether it is a flat-lay, hanger, mannequin, or shows a different person wearing it, it does not matter. You must extract ONLY the garment design from Image 2 and apply it to the person in Image 1. "
            "TASK: generate a brand-new image of the person from Image 1 dressed in the garment from Image 2. "
            "IDENTITY RULE — non-negotiable: "
            "The face, hair and body in the result belong to the person from Image 1 — not to any person in Image 2. "
            "If Image 2 shows a person wearing the garment: that person is irrelevant. Their face and body must NOT appear in the result. "
            "The result is a completely new photo of the Image 1 person. It is not Image 2 and not a modification of Image 2. "
            ""
            "PHYSICAL INTEGRATION — this is the most important quality requirement: "
            "The garment must be rendered as a real 3D object worn on the model's body — NOT as a 2D image pasted or composited over Image 1. "
            "• The fabric wraps around and conforms to the model's 3D body contours: shoulders, chest, waist, arms. "
            "• Natural creases, folds and wrinkles MUST appear at every stress point: armpits, inner elbows, shoulder area, waist, around buttons and zips. A perfectly smooth, flat garment looks fake and composited — it is not acceptable. "
            "• Fabric physics: heavy fabrics (denim, leather, thick wool) fall with structured weight and stiffness; light fabrics (cotton jersey, linen, chiffon, silk) drape softly and may cling or flow. Apply the correct physics for the fabric type from Image 2. "
            "• The garment casts micro-shadows where it folds onto itself, and contact shadows where it meets the model's body (collar on neck, sleeves on arms). "
            "• Garment edges must blend seamlessly with the model's body and surroundings — no hard cutouts, floating outlines or unnatural boundaries. "
            "• All lighting on the garment (highlights, shadows, sheen) must be consistent with the scene light source in Image 1. "
            "• The final image must be indistinguishable from a real photograph of this person wearing this garment. "
            ""
            f"{body_zone}"
            ""
            "ACCESSORIES & FOOTWEAR: Preserve all accessories (jewellery, bags, sunglasses, belts, scarves) "
            "and footwear visible in Image 1 unless Image 2 directly replaces them. "
            ""
            "SLEEVE RULES — HIGHEST PRIORITY for design accuracy: "
            "The sleeves must match Image 2 exactly: "
            "shoulder join type (set-in / raglan / drop-shoulder / kimono), "
            "length (cap / short / elbow / 3-quarter / long), "
            "width at shoulder, width at cuff, taper, cuff style and colour, "
            "any sleeve design elements (stripes, colour-blocks, patches, prints). "
            "FLAT-LAY RULE: if Image 2 shows sleeves extending horizontally, they hang vertically when worn — "
            "determine worn proportions from the cuff-to-shoulder distance in Image 2. "
            "NEVER copy sleeve shape or length from Image 1. "
            ""
            "GARMENT DESIGN — reproduce every design element from Image 2 faithfully: "
            "COLOUR: exact hue and saturation per zone — do not shift, warm, cool or desaturate. "
            "Scene lighting affects only shadow depth and highlight brightness, never hue or saturation. "
            "SEAMS & CONSTRUCTION: all seams, topstitching, overlock edges, darts exactly as in Image 2. "
            "CLOSURES: every button, zip, snap or tie — shape, colour, count and position. "
            "LOGO / GRAPHIC / TEXT / EMBROIDERY: size, colour, position and orientation from Image 2 — do not redraw, rescale or reposition. "
            "SILHOUETTE & FIT: oversized / boxy / relaxed / regular / slim / tailored — exact, do not normalise. "
            "NECKLINE & COLLAR: exact type and shape from Image 2. "
            "HEM: exact length and shape from Image 2. "
            "FABRIC appearance (texture, sheen): match Image 2. Do NOT copy product-photo shadows or backgrounds. "
            "LABELS, PATCHES, HARDWARE: all visible details from Image 2 must appear. "
            ""
            f"{checklist}"
            ""
            "MODEL: preserve from Image 1 — face, skin tone, hair, body proportions, pose. "
            "Do not alter body shape. "
            ""
            "ABSOLUTE CONSTRAINTS: "
            "1. Output is a newly generated image of the person from Image 1 wearing the garment — not Image 2 or any modification of it. "
            "2. Do not hallucinate garment details — Image 2 and the checklist are the only design authority. "
            f"3. Photorealistic result.{season_text}{sizes_text} "
            "Output: one image."
        )
    else:
        # Outfit: user is intentionally building a full look — replace all clothing
        checklists = "".join(
            _checklist_block(desc, f"GARMENT {i+1} (Image {i+2})")
            for i, desc in enumerate(descs)
        )
        prompt = (
            "Virtual try-on. "
            "Image 1 = the person whose face and body must appear in the final result. "
            f"Images 2 to {n+1} = garment design sources ONLY — extract ONLY the garment designs, regardless of how the items are shown (flat-lay, hanger, mannequin, or a different person wearing them). "
            "TASK: generate a brand-new image of the person from Image 1 dressed in all garments from Images 2 onwards. "
            "IDENTITY RULE — non-negotiable: "
            "The face, hair and body in the result belong to the person from Image 1 — not to any person in Images 2+. "
            "If any garment image shows a person wearing it: that person is irrelevant. Their face and body must NOT appear in the result. "
            "The result is a completely new photo of the Image 1 person. It is not any of the garment images and not a modification of them. "
            ""
            "PHYSICAL INTEGRATION — most important quality requirement: "
            "Every garment must be rendered as a real 3D object worn on the model's body — NOT as a 2D image pasted or composited over Image 1. "
            "• Fabric wraps around and conforms to the model's 3D body contours: shoulders, chest, waist, arms, hips. "
            "• Natural creases, folds and wrinkles MUST appear at every stress point: armpits, inner elbows, shoulder area, waist, around closures. A smooth, flat garment looks fake — it is not acceptable. "
            "• Fabric physics: heavy fabrics fall with weight and structure; light fabrics drape softly. Apply correct physics per fabric type from each source image. "
            "• Each garment casts micro-shadows at folds and contact shadows where it meets the body. "
            "• All garment edges blend seamlessly — no hard cutouts, floating outlines or unnatural boundaries. "
            "• All lighting on all garments must share the same light source from Image 1. "
            "• The final image must be indistinguishable from a real photograph of this person wearing this outfit. "
            ""
            "ACCESSORIES & FOOTWEAR: Preserve all accessories and footwear from Image 1 unless garment images replace them. "
            ""
            "SLEEVE RULES — HIGHEST PRIORITY for design accuracy: "
            "For every garment, sleeves must match the source image exactly: "
            "shoulder join type (set-in / raglan / drop-shoulder / kimono), "
            "length, width at shoulder, width at cuff, taper, cuff style and colour, sleeve design elements. "
            "FLAT-LAY RULE: horizontal sleeves in the photo = vertical when worn. "
            "NEVER copy sleeve shape from Image 1. "
            ""
            "EACH GARMENT DESIGN — reproduce every design element faithfully from its source image: "
            "COLOUR: exact hue and saturation per zone — do not shift, warm, cool or desaturate. "
            "Scene lighting affects only shadow depth and highlight brightness, never hue or saturation. "
            "SEAMS & CONSTRUCTION: all seams, topstitching, overlock edges, darts. "
            "CLOSURES: every button, zip, snap or tie — shape, colour, count, position. "
            "LOGO / GRAPHIC / TEXT / EMBROIDERY: size, colour, position, orientation — do not redraw or rescale. "
            "SILHOUETTE & FIT: exact per garment — do not normalise. "
            "NECKLINE & COLLAR, HEM: exact per garment image. "
            "FABRIC texture and sheen: match source image. Do NOT copy product-photo shadows or backgrounds. "
            "LABELS, PATCHES, HARDWARE: all visible details must appear. "
            ""
            "LAYERING: natural layering order (shirt under jacket, belt over trousers). "
            ""
            f"{checklists}"
            ""
            "MODEL: preserve from Image 1 — face, skin tone, hair, body proportions, pose. Do not alter body shape. "
            ""
            "ABSOLUTE CONSTRAINTS: "
            "1. Output is a newly generated image of the person from Image 1 — not any garment image or modification. "
            "2. Do not hallucinate garment details — source images and checklists are the only design authority. "
            f"3. Photorealistic result.{season_text}{sizes_text} "
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
