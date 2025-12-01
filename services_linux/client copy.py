import os
import requests
from pathlib import Path

LOCAL_DIR = Path("./local_data")
SERVER_API_URL = "http://13.38.48.162:8000/sync/files"

def get_server_files():
    response = requests.get(SERVER_API_URL)
    response.raise_for_status()
    return response.json()

def download_file(url, destination):
    """
    Télécharge un fichier via lien S3.
    Si le parent est un fichier, le supprime.
    Ignore les destinations qui sont des dossiers (pseudo-dossiers S3).
    """
    if str(destination).endswith(os.sep):
        return

    parent = destination.parent
    if parent.exists() and parent.is_file():
        parent.unlink()

    parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.is_dir():
        return

    r = requests.get(url, stream=True)
    r.raise_for_status()

    with open(destination, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)

def sync():
    server_files = get_server_files()
    server_filenames = set(server_files.keys())

    local_files = set()
    for root, _, files in os.walk(LOCAL_DIR):
        for file in files:
            rel_path = Path(root).relative_to(LOCAL_DIR) / file
            local_files.add(rel_path.as_posix())

    missing_files = server_filenames - local_files
    extra_files = local_files - server_filenames

    for filename in sorted(missing_files):
        url = server_files[filename]
        dest = LOCAL_DIR / filename
        download_file(url, dest)

    for filename in sorted(extra_files):
        path = LOCAL_DIR / filename
        os.remove(path)


if __name__ == "__main__":
    LOCAL_DIR.mkdir(exist_ok=True)
    sync()
