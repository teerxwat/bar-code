import subprocess, re, socket, ipaddress

def find_ip_by_mac(target_mac: str, subnet: str = "192.168.1.0/24") -> str | None:
    """หา IP ของเครื่องจาก MAC address (เครื่องต้องอยู่ subnet เดียวกัน)"""
    norm = target_mac.lower().replace(":", "-")

    # ping sweep เพื่อ populate ตาราง ARP ก่อน (เครื่อง Windows)
    for ip in ipaddress.ip_network(subnet).hosts():
        subprocess.Popen(["ping", "-n", "1", "-w", "100", str(ip)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # อ่านตาราง ARP แล้วจับคู่ MAC
    out = subprocess.run(["arp", "-a"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        m = re.search(r"(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F-]{17})", line)
        if m and m.group(2).lower() == norm:
            return m.group(1)
    return None


# ใช้งาน
ip = find_ip_by_mac("00:1B:82:XX:XX:XX")   # ใส่ MAC จริงของเครื่อง
if ip:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((ip, 9100))
        s.sendall(build_tspl())     # build_tspl() จากสคริปต์เดิม
        print(f"ปริ้นไปที่ {ip} เรียบร้อย")
else:
    print("หาเครื่องไม่เจอ — เช็คว่าอยู่ subnet เดียวกันและ MAC ถูกต้อง")