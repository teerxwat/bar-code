"""
สร้างตัวติดตั้ง Windows ของ print server (รันบนเครื่อง Windows เท่านั้น — PyInstaller
แพ็กข้ามระบบปฏิบัติการไม่ได้) ปกติเรียกผ่าน build.bat หรือ GitHub Actions

ขั้นตอน:
  1) PyInstaller แพ็ก tsc_te310_print_server.py + Python + library + ฟอนต์ไทย
     เป็นโฟลเดอร์ build/dist/MaeWang-SmartPay/ (มี MaeWang-SmartPay.exe ข้างใน)
  2) Inno Setup (ISCC.exe) ห่อโฟลเดอร์นั้นเป็นตัวติดตั้งไฟล์เดียว
     output/MaeWang-SmartPay-Setup-<version>.exe
  3) เขียน output/latest.json (เวอร์ชัน + ชื่อไฟล์ + sha256) สำหรับระบบอัปเดตของแอป

เลขเวอร์ชันอ่านจาก __version__ ใน tsc_te310_print_server.py
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPT = os.path.join(ROOT, "tsc_te310_print_server.py")
FONT = os.path.join(ROOT, "NotoSansThai-Variable.ttf")
BUILD_DIR = os.path.join(HERE, "build")
APP_NAME = "MaeWang-SmartPay"


def read_version() -> str:
    with open(SCRIPT, encoding="utf-8") as f:
        m = re.search(r'^__version__ = "([^"]+)"', f.read(), re.M)
    if not m:
        sys.exit("หา __version__ ใน tsc_te310_print_server.py ไม่เจอ")
    return m.group(1)


def read_print_key():
    """SMARTPAY_PRINT_KEY ที่จะฝังไปกับตัวติดตั้ง — เอาจาก env var ก่อน (ใช้ตอน build บน
    GitHub Actions ผ่าน secret) ไม่มีค่อยอ่านจาก .env ของโปรเจกต์ ไม่เจอเลยคืน None"""
    key = os.environ.get("SMARTPAY_PRINT_KEY", "").strip()
    env_path = os.path.join(ROOT, ".env")
    if not key and os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                name, _, value = line.strip().partition("=")
                if name.strip() == "SMARTPAY_PRINT_KEY":
                    key = value.strip().strip('"').strip("'")
    return key or None


def write_default_env():
    """เขียน build/default.env (มีแค่ SMARTPAY_PRINT_KEY — ค่าอื่นใน .env เช่น
    SMARTPAY_ADMIN_JWT / TSC_MOCK ไม่เอาไปด้วย) ให้ installer.iss หยิบไปติดตั้ง"""
    path = os.path.join(BUILD_DIR, "default.env")
    key = read_print_key()
    if not key:
        if os.path.exists(path):
            os.remove(path)
        print("*** ไม่พบ SMARTPAY_PRINT_KEY (env var หรือ .env) — ตัวติดตั้งจะไม่มีคีย์ฝังไปด้วย")
        return
    os.makedirs(BUILD_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# ค่าเริ่มต้นจากตัวติดตั้ง — ห้ามแก้ไฟล์นี้ (ถูกเขียนทับตอนอัปเดต) ตั้งค่าเองให้ใส่ใน .env\n")
        f.write(f"SMARTPAY_PRINT_KEY={key}\n")
    print("ฝัง SMARTPAY_PRINT_KEY ไปกับตัวติดตั้ง (default.env)")


def find_iscc():
    found = shutil.which("iscc")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        if base:
            path = os.path.join(base, "Inno Setup 6", "ISCC.exe")
            if os.path.exists(path):
                return path
    return None


def main():
    version = read_version()
    print(f"=== build {APP_NAME} v{version} ===")

    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--name", APP_NAME,
        "--console",  # ให้เห็น log ของ print server — ปิดหน้าต่าง = หยุด server
        "--icon", os.path.join(HERE, "app.ico"),
        "--add-data", f"{FONT}{os.pathsep}.",
        "--collect-all", "libusb_package",  # libusb-1.0.dll สำหรับคุย USB
        "--collect-all", "barcode",         # ใช้วาดบาร์โค้ดในพรีวิว mock mode
        "--hidden-import", "usb.backend.libusb1",
        "--distpath", os.path.join(BUILD_DIR, "dist"),
        "--workpath", os.path.join(BUILD_DIR, "work"),
        "--specpath", BUILD_DIR,
        SCRIPT,
    ], check=True)

    write_default_env()  # หลัง PyInstaller เพราะ --clean ไม่แตะไฟล์นี้ แต่ต้องมี build/ ก่อน

    if sys.platform != "win32":
        print("ไม่ใช่ Windows — ข้ามขั้นตอนสร้างตัวติดตั้ง (Inno Setup)")
        return
    iscc = find_iscc()
    if not iscc:
        sys.exit("ไม่พบ Inno Setup 6 (ISCC.exe) — ติดตั้งจาก https://jrsoftware.org/isdl.php แล้วรันใหม่")
    subprocess.run([iscc, f"/DAppVersion={version}", os.path.join(HERE, "installer.iss")], check=True)
    # latest.json — แอปที่ติดตั้งไปแล้วอ่านไฟล์นี้เพื่อเช็กเวอร์ชันใหม่ (ดู UPDATE_MANIFEST_URL)
    # ต้องอัปโหลดคู่กับตัวติดตั้งไว้ที่เดียวกันเสมอ
    setup_name = f"{APP_NAME}-Setup-{version}.exe"
    setup_path = os.path.join(HERE, "output", setup_name)
    with open(setup_path, "rb") as f:
        sha256 = hashlib.sha256(f.read()).hexdigest()
    with open(os.path.join(HERE, "output", "latest.json"), "w", encoding="utf-8") as f:
        json.dump({"version": version, "file": setup_name, "sha256": sha256}, f, indent=2)
    print(f"\nเสร็จแล้ว: {setup_path}\n        + latest.json (อัปโหลดคู่กันเพื่อให้แอปเช็กอัปเดตได้)")


if __name__ == "__main__":
    main()
