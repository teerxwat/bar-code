"""
TSC TE310 — ป้ายการ์ด (แนวนอน 50x30 mm) หัวภาษาไทย + บาร์โค้ดใหญ่ ผ่าน USB บน macOS
render ด้วย Pillow -> ส่งเป็น BITMAP + BARCODE ของเครื่อง

ติดตั้งก่อน:
    brew install libusb
    pip install pyusb pillow

วิธีรัน:
    python tsc_te310_usb_direct.py
    # ถ้า Access denied ให้ลอง: sudo python tsc_te310_usb_direct.py
"""
import os
import sys
import usb.core
import usb.util
from PIL import Image, ImageDraw, ImageFont

# ============== ข้อความบนป้าย (แก้ตรงนี้) ==============
TITLE        = "เทศบาลตำบลแม่วาง"
KEY_LABEL    = "PERSONAL KEY"
KEY_VALUE    = "PK-1000482"
BARCODE_DATA = "PK-1000482"          # ข้อมูลในบาร์โค้ด (Code128)
# ======================================================

# ============== ค่าเครื่อง / ขนาด ==============
VENDOR_ID  = None        # ใส่ถ้าหาเครื่องไม่เจอ เช่น 0x1203
PRODUCT_ID = None
DENSITY = 10             # ความเข้ม 0-15
SPEED   = 3
W, H = 590, 354          # 50mm x 30mm ที่ 300 dpi
INVERT_BITMAP = False    # ถ้าพิมพ์ออกมาพื้นดำตัวขาว ให้เปลี่ยนเป็น True

# บาร์โค้ด (ขยายใหญ่)
BAR_NARROW = 3           # ความกว้างแท่ง: 2=เล็ก 3=กลาง 4=เกือบเต็ม
BAR_Y      = 115
BAR_HEIGHT = 150         # ความสูง (เพิ่มเลขนี้ให้ใหญ่ขึ้นได้อีก)
# ===============================================

# ฟอนต์ไทยสำหรับหัวเรื่อง (macOS) — มี fallback อัตโนมัติ
THAI_FONTS = [
    "/System/Library/Fonts/SukhumvitSet.ttc",
    "/System/Library/Fonts/Supplemental/Thonburi.ttc",
    os.path.expanduser("~/Library/Fonts/Sarabun-Bold.ttf"),
    os.path.expanduser("~/Library/Fonts/IBMPlexSansThai-Bold.ttf"),
    "/Library/Fonts/Sarabun-Bold.ttf",
]
TITLE_INDEX = 0          # SukhumvitSet: ลองเปลี่ยนเป็น 5 เพื่อให้หนาขึ้น
SANS = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]
MONO_BOLD = [
    "/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Menlo.ttc",
]


def load_font(paths, size, index=0):
    for p in paths:
        try:
            return ImageFont.truetype(p, size, index=index,
                                      layout_engine=ImageFont.Layout.RAQM)
        except Exception:
            try:
                return ImageFont.truetype(p, size, index=index)
            except Exception:
                continue
    return ImageFont.load_default()


def draw_tracked(draw, xy, text, font, tracking=0, fill=0, align="left"):
    """วาดข้อความพร้อมระยะห่างตัวอักษร (letter-spacing); align: left/right/center"""
    widths = [draw.textlength(c, font=font) for c in text]
    total = sum(widths) + tracking * max(0, len(text) - 1)
    x, y = xy
    if align == "right":
        x -= total
    elif align == "center":
        x -= total / 2
    for c, w in zip(text, widths):
        draw.text((x, y), c, font=font, fill=fill)
        x += w + tracking
    return total


def render_label_bitmap() -> Image.Image:
    img = Image.new("1", (W, H), 1)        # 1 = ขาว
    d = ImageDraw.Draw(img)

    title_f  = load_font(THAI_FONTS, 44, index=TITLE_INDEX)
    keylbl_f = load_font(SANS, 15)
    key_f    = load_font(MONO_BOLD, 44)

    # --- หัวการ์ด (ภาษาไทย, ชิดซ้าย) ---
    d.text((30, 24), TITLE, font=title_f, fill=0)
    d.rectangle([30, 100, W - 30, 104], fill=0)     # เส้นหนาใต้หัว

    # --- เส้นบางเหนือ footer ---
    d.rectangle([30, 270, W - 30, 271], fill=0)

    # --- footer ---
    draw_tracked(d, (30, 302), KEY_LABEL, keylbl_f, tracking=3, fill=0, align="left")
    draw_tracked(d, (W - 28, 288), KEY_VALUE, key_f, tracking=1, fill=0, align="right")

    # (พื้นที่บาร์โค้ดเว้นว่างไว้ ให้คำสั่ง BARCODE ของเครื่องวาดทับ)
    return img


def build_tspl() -> bytes:
    img = render_label_bitmap()
    if INVERT_BITMAP:
        img = img.point(lambda v: 255 - v)

    wbytes = (W + 7) // 8
    data = img.tobytes()

    # คำนวณความกว้างบาร์โค้ด Code128 เพื่อจัดกึ่งกลาง
    modules = 11 + 11 * len(BARCODE_DATA) + 11 + 13
    bar_w = modules * BAR_NARROW
    bx = max(10, (W - bar_w) // 2)

    head = (
        f"SIZE 50 mm, 30 mm\r\nGAP 2 mm, 0 mm\r\nDIRECTION 1\r\n"
        f"REFERENCE 0,0\r\nDENSITY {DENSITY}\r\nSPEED {SPEED}\r\nCLS\r\n"
    ).encode()
    bmp = f"BITMAP 0,0,{wbytes},{H},0,".encode() + data + b"\r\n"
    # BARCODE x,y,"type",height,human,rotation,narrow,wide,"data"
    bc = (f'BARCODE {bx},{BAR_Y},"128",{BAR_HEIGHT},0,0,'
          f'{BAR_NARROW},{BAR_NARROW},"{BARCODE_DATA}"\r\n').encode()
    tail = b"PRINT 1,1\r\n"
    return head + bmp + bc + tail


# ============== ส่วนเชื่อมต่อ USB ==============
def _safe_string(dev, index):
    try:
        return (usb.util.get_string(dev, index) or "").upper()
    except Exception:
        return ""


def _is_printer(dev):
    try:
        if dev.bDeviceClass == 7:
            return True
        for cfg in dev:
            for intf in cfg:
                if intf.bInterfaceClass == 7:
                    return True
    except Exception:
        pass
    return False


def dump_devices(devs):
    print("USB devices ที่เห็น:")
    for d in devs:
        manu = _safe_string(d, d.iManufacturer)
        prod = _safe_string(d, d.iProduct)
        tag = " [printer]" if _is_printer(d) else ""
        print(f"  VID={hex(d.idVendor)} PID={hex(d.idProduct)} {manu} {prod}{tag}")


def find_printer():
    if VENDOR_ID and PRODUCT_ID:
        dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
        if dev:
            return dev
    candidates = list(usb.core.find(find_all=True))
    for dev in candidates:
        manu = _safe_string(dev, dev.iManufacturer)
        prod = _safe_string(dev, dev.iProduct)
        if "TSC" in manu or "TSC" in prod or "TE310" in prod:
            return dev
    printers = [d for d in candidates if _is_printer(d)]
    if len(printers) == 1:
        return printers[0]
    if len(printers) > 1:
        print("เจออุปกรณ์คลาส printer มากกว่า 1 ตัว — เลือกด้วย VID/PID:")
        for d in printers:
            print(f"  VID={hex(d.idVendor)} PID={hex(d.idProduct)}")
        return None
    dump_devices(candidates)
    return None


def send(dev, data: bytes):
    try:
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
    except (NotImplementedError, usb.core.USBError):
        pass
    dev.set_configuration()
    cfg = dev.get_active_configuration()
    intf = cfg[(0, 0)]
    ep_out = usb.util.find_descriptor(
        intf,
        custom_match=lambda e:
            usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT,
    )
    if ep_out is None:
        raise RuntimeError("ไม่เจอ bulk OUT endpoint")
    written = ep_out.write(data, timeout=10000)
    usb.util.dispose_resources(dev)
    return written


def main():
    dev = find_printer()
    if dev is None:
        print("หาเครื่อง TSC ผ่าน USB ไม่เจอ — ดู VID/PID: system_profiler SPUSBDataType | grep -A 12 -i tsc")
        sys.exit(1)
    print(f"เจอเครื่อง: VID={hex(dev.idVendor)} PID={hex(dev.idProduct)} — กำลังส่งคำสั่งปริ้น...")
    try:
        n = send(dev, build_tspl())
        print(f"ส่งคำสั่งปริ้นเรียบร้อย ({n} bytes)")
    except usb.core.USBError as e:
        print(f"ส่งไม่สำเร็จ (USBError): {e}  -> ลอง sudo หรือถอด-เสียบสาย USB ใหม่")
        sys.exit(1)


if __name__ == "__main__":
    main()