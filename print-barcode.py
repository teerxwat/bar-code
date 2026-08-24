"""
TSC TE310 — สั่งทดสอบปริ้นผ่าน USB ตรงด้วย libusb/pyusb (macOS รุ่นใหม่)
ใช้เมื่อ CUPS ใช้ raw queue ไม่ได้ ("Raw queues are no longer supported")
ฉลากขนาด 3x5 cm, TSPL2, 300 dpi

ติดตั้งก่อน:
    brew install libusb
    pip install pyusb

วิธีรัน:
    python tsc_te310_usb_direct.py
    # ถ้าเจอ Access denied ให้ลอง: sudo python tsc_te310_usb_direct.py
"""
import sys
import usb.core
import usb.util

# ============== CONFIG ==============
# ปล่อย None ไว้เพื่อให้ค้นหาอัตโนมัติจากชื่อ TSC
# ถ้าหาไม่เจอ ให้ใส่ค่าจาก system_profiler SPUSBDataType (เลขฐาน 16)
VENDOR_ID  = None      # เช่น 0x1203
PRODUCT_ID = None      # เช่น 0x0230

DENSITY = 10           # ความเข้ม 0-15
SPEED   = 3            # ความเร็วพิมพ์
# ===================================


def build_tspl() -> bytes:
    """ฉลากทดสอบแบบแนวนอน — ป้ายกว้าง 50mm x สูง 30mm
    (กว้าง = ตามแนวหัวพิมพ์ 590 dots, สูง = ตามแนวป้อนกระดาษ 354 dots ที่ 300 dpi)
    ใช้ข้อความแนวปกติ rotation 0 เพราะพื้นที่พิมพ์เป็นแนวนอนอยู่แล้ว
    """
    tspl = (
        "SIZE 50 mm, 30 mm\r\n"       # กว้าง 5cm สูง 3cm = ตรงกับป้ายจริง
        "GAP 2 mm, 0 mm\r\n"          # ระยะ gap ระหว่างป้าย (ปรับตามม้วนจริง)
        "DIRECTION 1\r\n"
        "REFERENCE 0,0\r\n"
        f"DENSITY {DENSITY}\r\n"
        f"SPEED {SPEED}\r\n"
        "CLS\r\n"
        'TEXT 40,30,"3",0,2,2,"TSC TE310"\r\n'
        'TEXT 40,95,"2",0,1,1,"Test Print 3x5 cm"\r\n'
        'BARCODE 40,135,"128",85,1,0,2,2,"123456789"\r\n'
        'TEXT 40,255,"2",0,1,1,"Donaus Co., Ltd."\r\n'
        'TEXT 40,300,"1",0,1,1,"Landscape 5x3 cm"\r\n'
        "BOX 10,10,580,344,3\r\n"     # กรอบรอบป้าย (พื้นที่ 590x354)
        "PRINT 1,1\r\n"
    )
    return tspl.encode("utf-8")


def _safe_string(dev, index):
    try:
        return (usb.util.get_string(dev, index) or "").upper()
    except Exception:
        return ""


def _is_printer(dev):
    """ตรวจว่าเป็นอุปกรณ์คลาส printer (7) โดยไม่ต้องอ่าน string descriptor"""
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
    """แสดงรายการ USB ทั้งหมด ไว้ดูตอนหาไม่เจอ"""
    print("USB devices ที่เห็น:")
    for d in devs:
        manu = _safe_string(d, d.iManufacturer)
        prod = _safe_string(d, d.iProduct)
        tag = " [printer]" if _is_printer(d) else ""
        print(f"  VID={hex(d.idVendor)} PID={hex(d.idProduct)} {manu} {prod}{tag}")


def find_printer():
    # 1) ถ้าระบุ VID/PID มาแล้ว ใช้ตรง ๆ
    if VENDOR_ID and PRODUCT_ID:
        dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
        if dev:
            return dev

    candidates = list(usb.core.find(find_all=True))

    # 2) จับจากชื่อ TSC/TE310 (ถ้าอ่าน string ได้)
    for dev in candidates:
        manu = _safe_string(dev, dev.iManufacturer)
        prod = _safe_string(dev, dev.iProduct)
        if "TSC" in manu or "TSC" in prod or "TE310" in prod:
            return dev

    # 3) จับจากคลาส printer (class 7) — ไม่ต้องอ่าน string
    printers = [d for d in candidates if _is_printer(d)]
    if len(printers) == 1:
        return printers[0]
    if len(printers) > 1:
        print("เจออุปกรณ์คลาส printer มากกว่า 1 ตัว — เลือกด้วย VID/PID:")
        for d in printers:
            print(f"  VID={hex(d.idVendor)} PID={hex(d.idProduct)}")
        return None

    # ไม่เจอเลย -> dump ทั้งหมดไว้ดู
    dump_devices(candidates)
    return None


def send(dev, data: bytes):
    # บน macOS ไม่ต้อง detach kernel driver (ห่อ try กันพังถ้า backend ไม่รองรับ)
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
        raise RuntimeError("ไม่เจอ bulk OUT endpoint บนเครื่องนี้")

    written = ep_out.write(data, timeout=5000)
    usb.util.dispose_resources(dev)
    return written


def main():
    dev = find_printer()
    if dev is None:
        print("หาเครื่อง TSC ผ่าน USB ไม่เจอ")
        print("→ เช็คว่าเสียบสาย USB และเปิดเครื่องอยู่")
        print("→ ดู VID/PID ด้วย: system_profiler SPUSBDataType | grep -A 12 -i tsc")
        print("  แล้วเอามาใส่ VENDOR_ID / PRODUCT_ID ในไฟล์")
        sys.exit(1)

    print(f"เจอเครื่อง: VID={hex(dev.idVendor)} PID={hex(dev.idProduct)} — กำลังส่งคำสั่งปริ้น...")
    try:
        n = send(dev, build_tspl())
        print(f"ส่งคำสั่งปริ้นเรียบร้อย ({n} bytes)")
    except usb.core.USBError as e:
        print(f"ส่งไม่สำเร็จ (USBError): {e}")
        print("→ ลองรันด้วย sudo, หรือถ้ามีคิว CUPS ของ TSC ค้างอยู่ให้ลบออกก่อน (เพราะมันจับเครื่องไว้)")
        sys.exit(1)


if __name__ == "__main__":
    main()