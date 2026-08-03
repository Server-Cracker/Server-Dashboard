from flask import Flask, jsonify, request, render_template
import psutil
import subprocess
import time
import os

app = Flask(__name__)

# Set this to something private. Override with: export DASHBOARD_TOKEN="yourtoken"
AUTH_TOKEN = os.environ.get("DASHBOARD_TOKEN", "changeme123")

# Containers/services you care about most - edit these names to match yours
HIGHLIGHT_CONTAINERS = ["teleplay", "adguard", "adguardhome"]


def check_auth(req):
    token = req.headers.get("X-Auth-Token") or req.args.get("token")
    if not token and req.is_json:
        token = (req.get_json(silent=True) or {}).get("token")
    return token == AUTH_TOKEN


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def status():
    cpu = psutil.cpu_percent(interval=0.4)
    per_core = psutil.cpu_percent(interval=0.0, percpu=True)
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage("/")
    boot_time = psutil.boot_time()
    uptime_seconds = time.time() - boot_time

    # --- Top processes by RAM ---
    top_processes = []
    try:
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'memory_percent', 'memory_info']):
            try:
                info = p.info
                if info['memory_info'] is None:
                    continue
                procs.append({
                    "pid": info['pid'],
                    "name": info['name'],
                    "memory_percent": round(info['memory_percent'], 1),
                    "memory_mb": round(info['memory_info'].rss / (1024 * 1024), 1)
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        procs.sort(key=lambda x: x['memory_mb'], reverse=True)
        top_processes = procs[:5]
    except Exception:
        top_processes = []

    # --- Overall health rollup ---
    # thresholds: >=90% = critical, >=75% = warning, else healthy
    def level(pct):
        if pct >= 90:
            return "critical"
        if pct >= 75:
            return "warning"
        return "healthy"

    cpu_level = level(cpu)
    mem_level = level(mem.percent)
    disk_level = level(disk.percent)

    severity_order = {"healthy": 0, "warning": 1, "critical": 2}
    worst = max([cpu_level, mem_level, disk_level], key=lambda l: severity_order[l])

    reasons = []
    if cpu_level != "healthy":
        reasons.append(f"CPU at {cpu:.0f}%")
    if mem_level != "healthy":
        reasons.append(f"RAM at {mem.percent:.0f}%")
    if disk_level != "healthy":
        reasons.append(f"Storage at {disk.percent:.0f}%")

    health = {
        "status": worst,
        "reasons": reasons,
        "checks": {"cpu": cpu_level, "memory": mem_level, "disk": disk_level}
    }

    try:
        load1, load5, load15 = os.getloadavg()
    except (OSError, AttributeError):
        load1 = load5 = load15 = 0

    try:
        temps = psutil.sensors_temperatures()
        cpu_temp = None
        for name, entries in temps.items():
            if entries:
                cpu_temp = entries[0].current
                break
    except Exception:
        cpu_temp = None

    return jsonify({
        "health": health,
        "cpu_percent": cpu,
        "cpu_cores": psutil.cpu_count(),
        "cpu_per_core": per_core,
        "cpu_temp_c": cpu_temp,
        "load_avg": {"1m": round(load1, 2), "5m": round(load5, 2), "15m": round(load15, 2)},
        "memory": {
            "total_gb": round(mem.total / (1024 ** 3), 2),
            "used_gb": round(mem.used / (1024 ** 3), 2),
            "available_gb": round(mem.available / (1024 ** 3), 2),
            "percent": mem.percent
        },
        "swap": {
            "total_gb": round(swap.total / (1024 ** 3), 2),
            "used_gb": round(swap.used / (1024 ** 3), 2),
            "percent": swap.percent
        },
        "disk": {
            "total_gb": round(disk.total / (1024 ** 3), 2),
            "used_gb": round(disk.used / (1024 ** 3), 2),
            "free_gb": round(disk.free / (1024 ** 3), 2),
            "percent": disk.percent
        },
        "uptime_seconds": int(uptime_seconds),
        "top_processes": top_processes
    })


@app.route("/api/docker")
def docker_status():
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}|{{.Status}}|{{.Image}}"],
            capture_output=True, text=True, timeout=5
        )
        containers = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|", 2)
            if len(parts) != 3:
                continue
            name, status_str, image = parts
            running = status_str.startswith("Up")
            highlighted = any(h in name.lower() for h in HIGHLIGHT_CONTAINERS)
            containers.append({
                "name": name,
                "status": status_str,
                "image": image,
                "running": running,
                "highlighted": highlighted
            })
        # highlighted ones first
        containers.sort(key=lambda c: (not c["highlighted"], c["name"]))
        return jsonify({"containers": containers})
    except FileNotFoundError:
        return jsonify({"error": "docker command not found on this system", "containers": []}), 500
    except Exception as e:
        return jsonify({"error": str(e), "containers": []}), 500


@app.route("/api/service/<name>")
def service_status(name):
    """Check a native systemd service (use this if AdGuard Home runs as a
    systemd service instead of a docker container)."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", name],
            capture_output=True, text=True, timeout=5
        )
        active = result.stdout.strip() == "active"
        return jsonify({"name": name, "active": active, "raw": result.stdout.strip()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/docker/restart/<container_name>", methods=["POST"])
def restart_container(container_name):
    if not check_auth(request):
        return jsonify({"error": "unauthorized"}), 401
    # Only allow restarting containers whose name matches our highlighted list,
    # to prevent this endpoint from being used to restart arbitrary containers.
    if not any(h in container_name.lower() for h in HIGHLIGHT_CONTAINERS):
        return jsonify({"error": "not permitted for this container"}), 403
    try:
        result = subprocess.run(
            ["docker", "restart", container_name],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return jsonify({"error": result.stderr.strip() or "restart failed"}), 500
        return jsonify({"message": f"{container_name} restarted"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/shutdown", methods=["POST"])
def shutdown():
    if not check_auth(request):
        return jsonify({"error": "unauthorized"}), 401
    try:
        subprocess.Popen(["sudo", "/sbin/shutdown", "-h", "now"])
        return jsonify({"message": "Shutdown initiated"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/restart", methods=["POST"])
def restart():
    if not check_auth(request):
        return jsonify({"error": "unauthorized"}), 401
    try:
        subprocess.Popen(["sudo", "/sbin/reboot"])
        return jsonify({"message": "Restart initiated"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050)
