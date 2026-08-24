# -*- coding: utf-8 -*-
"""
พิมพ์ไฟล์รูปลงสติกเกอร์ 50x30 mm บนเครื่อง TSC TE310 (300 dpi) — macOS
ส่ง TSPL ตรงเข้า USB ด้วย pyusb + รองรับลายน้ำ (จำลองสีเทาด้วย dithering)

ติดตั้งก่อนใช้:
    brew install libusb
    pip install pillow pyusb

วิธีใช้:
    python wherery.py "ไฟล์รูป.png" [จำนวน]            พิมพ์
    python wherery.py "ไฟล์รูป.png" --preview          ไม่พิมพ์ แค่เซฟ preview.png ให้ดูก่อน
"""

import sys
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

# ---------- ตั้งค่า ----------
TSC_VENDOR_ID = 0x1203
LABEL_W_MM    = 50
LABEL_H_MM    = 30
GAP_MM        = 3
DPI           = 300
DITHER        = True          # ต้องเป็น True ถึงจะเห็นลายน้ำเป็นเทาจางๆ

# --- ลายน้ำ (ตั้งอย่างใดอย่างหนึ่ง หรือปิดทั้งคู่ก็ได้) ---
WATERMARK_TEXT    = "wherery"   # ข้อความลายน้ำ, ตั้ง None ถ้าไม่ใช้
WATERMARK_IMAGE   = None        # path โลโก้ .png, ตั้ง None ถ้าไม่ใช้
WATERMARK_OPACITY = 0.35        # ตัวเล็กๆ ต้องเข้มหน่อยถึงอ่านออก (คำใหญ่ใช้ ~0.18)
WATERMARK_ANGLE   = 20          # องศาเอียง
WATERMARK_TILE    = True        # True = ตัวเล็กๆ เรียงซ้ำเต็มแผ่น, False = คำใหญ่กลางแผ่น
TILE_FONT_SIZE    = 26          # ขนาดตัวอักษร (dot) ตอน tile — 300dpi: 26 ≈ 2.2 mm
TILE_SPACING_X    = 18          # ระยะห่างแนวนอนระหว่างคำ (dot)
TILE_SPACING_Y    = 14          # ระยะห่างแนวตั้งระหว่างแถว (dot)
FONT_PATH         = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
# -----------------------------

DOTS_PER_MM = DPI / 25.4


def apply_watermark(img: Image.Image) -> Image.Image:
    """วางลายน้ำ (ข้อความหรือโลโก้) ทับรูปแบบจางๆ ก่อน dithering"""
    img = img.convert("RGBA")
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))

    if WATERMARK_IMAGE:
        wm = Image.open(WATERMARK_IMAGE).convert("RGBA")
        # ย่อโลโก้ให้กว้าง ~60% ของสติกเกอร์
        ratio = (img.width * 0.6) / wm.width
        wm = wm.resize((int(wm.width * ratio), int(wm.height * ratio)), Image.LANCZOS)
        alpha = wm.getchannel("A").point(lambda a: int(a * WATERMARK_OPACITY))
        wm.putalpha(alpha)
        pos = ((img.width - wm.width) // 2, (img.height - wm.height) // 2)
        layer.paste(wm, pos, wm)

    elif WATERMARK_TEXT:
        size = TILE_FONT_SIZE if WATERMARK_TILE else int(img.height * 0.35)
        try:
            font = ImageFont.truetype(FONT_PATH, size=size)
        except OSError:
            font = ImageFont.load_default()
        txt = Image.new("RGBA", (img.width * 2, img.height * 2), (0, 0, 0, 0))
        d = ImageDraw.Draw(txt)
        bbox = d.textbbox((0, 0), WATERMARK_TEXT, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        fill = (0, 0, 0, int(255 * WATERMARK_OPACITY))

        if WATERMARK_TILE:
            # เรียงคำซ้ำเต็มผืน สลับเยื้องครึ่งคำแบบก่ออิฐ
            step_x = tw + TILE_SPACING_X
            step_y = th + TILE_SPACING_Y
            row = 0
            for y in range(0, txt.height, step_y):
                offset = (step_x // 2) if row % 2 else 0
                for x in range(-step_x, txt.width, step_x):
                    d.text((x + offset, y), WATERMARK_TEXT, font=font, fill=fill)
                row += 1
        else:
            d.text(
                ((txt.width - tw) // 2 - bbox[0], (txt.height - th) // 2 - bbox[1]),
                WATERMARK_TEXT,
                font=font,
                fill=fill,
            )

        txt = txt.rotate(WATERMARK_ANGLE, resample=Image.BICUBIC)
        layer.paste(
            txt,
            ((img.width - txt.width) // 2, (img.height - txt.height) // 2),
            txt,
        )

    return Image.alpha_composite(img, layer).convert("L")


def prepare_image(path: str) -> Image.Image:
    """โหลดรูป -> ย่อเป็นขนาดสติกเกอร์ -> ใส่ลายน้ำ -> แปลงขาวดำ 1 bit"""
    w_dots = int(LABEL_W_MM * DOTS_PER_MM)
    h_dots = int(LABEL_H_MM * DOTS_PER_MM)
    w_dots -= w_dots % 8

    img = Image.open(path).convert("L")
    img = img.resize((w_dots, h_dots), Image.LANCZOS)

    if WATERMARK_TEXT or WATERMARK_IMAGE:
        img = apply_watermark(img)

    if DITHER:
        return img.convert("1")
    return img.point(lambda p: 255 if p > 128 else 0).convert("1")


def image_to_tspl_bitmap(img: Image.Image) -> bytes:
    data = img.tobytes()  # TSPL: bit 1 = ขาว, bit 0 = ดำ — ตรงกับโหมด '1' ของ Pillow
    header = f"BITMAP 0,0,{img.width // 8},{img.height},0,".encode("ascii")
    return header + data + b"\r\n"


def build_tspl(img: Image.Image, copies: int = 1) -> bytes:
    cmd = (
        f"SIZE {LABEL_W_MM} mm,{LABEL_H_MM} mm\r\n"
        f"GAP {GAP_MM} mm,0 mm\r\n"
        "DIRECTION 1\r\n"
        "DENSITY 8\r\n"
        "SPEED 4\r\n"
        "CLS\r\n"
    ).encode("ascii")
    cmd += image_to_tspl_bitmap(img)
    cmd += f"PRINT 1,{copies}\r\n".encode("ascii")
    return cmd


def send_to_usb(data: bytes):
    import usb.core, usb.util

    dev = usb.core.find(idVendor=TSC_VENDOR_ID)
    if dev is None:
        sys.exit("ไม่เจอเครื่องพิมพ์ TSC ทาง USB — เช็คสาย/เปิดเครื่องหรือยัง")
    try:
        dev.set_configuration()
    except Exception:
        pass
    cfg = dev.get_active_configuration()
    intf = cfg[(0, 0)]
    ep_out = usb.util.find_descriptor(
        intf,
        custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
        == usb.util.ENDPOINT_OUT,
    )
    if ep_out is None:
        sys.exit("หา USB OUT endpoint ไม่เจอ")
    CHUNK = 4096
    for i in range(0, len(data), CHUNK):
        ep_out.write(data[i : i + CHUNK], timeout=10000)
    usb.util.dispose_resources(dev)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('วิธีใช้: python wherery.py "ไฟล์รูป" [จำนวน | --preview]')
        sys.exit(1)

    image_path = sys.argv[1]
    img = prepare_image(image_path)

    if len(sys.argv) > 2 and sys.argv[2] == "--preview":
        img.save("preview.png")
        print("เซฟตัวอย่างที่ preview.png แล้ว (ยังไม่ได้พิมพ์)")
    else:
        copies = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        send_to_usb(build_tspl(img, copies))
        print(f"ส่งพิมพ์แล้ว: {image_path} x{copies} ({LABEL_W_MM}x{LABEL_H_MM} mm)")