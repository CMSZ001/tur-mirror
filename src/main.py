#!/usr/local/bin/python3
"""
generate index.html with GitHub API (apply to all subfolders under dists/ and pool/)
"""
import os
import sys
import json
import base64
import datetime as dt
import requests
import re

with open('/src/icons.json', encoding="utf-8") as json_file:
    data = json.load(json_file)


GITHUB_REPO = "termux-user-repository/dists"
GITHUB_API = "https://api.github.com/repos/" + GITHUB_REPO
DEFAULT_RELEASE_TAG = "0.1"

# debug json cache (overwritten every run)
COMMITS_JSON = "dists_commits.json"
RELEASE_JSON = "pool_release.json"

_commits_cache = None
_release_cache = None
_all_releases = None


def main():
    global _all_releases
    if len(sys.argv) > 1:
        print("changing directory to " + sys.argv[1])
        try:
            os.chdir(sys.argv[1])
        except OSError:
            print("Cannot change the current working Directory")
            sys.exit()
    else:
        print("no directory specified")
        sys.exit()

    # 预先获取所有 release 列表
    _all_releases = fetch_all_releases()

    for dirname, dirnames, filenames in os.walk('.'):
        abs_dir = os.path.abspath(dirname)

        # 动态判断 mode（包含 dists 或 pool 的路径都算）
        if "/dists" in abs_dir:
            mode = "dists"
            if _commits_cache is None:
                fetch_commits_cache()
        elif "/pool" in abs_dir:
            mode = "pool"
            if _release_cache is None:
                fetch_release_cache()
        else:
            mode = "other"

        if 'index.html' in filenames:
            print(f"{dirname}/index.html already exists, skipping...")
            continue

        print(f"{dirname}/index.html does not exist, generating")
        with open(os.path.join(dirname, 'index.html'), 'w', encoding="utf-8") as f:
            f.write("\n".join([
                get_template_head(dirname),
                "<tr class=\"w-2/4 bg-white border-b hover:bg-gray-50\"><th scope=\"row\" class=\" py-2 px-2 lg:px-6 font-medium text-gray-900 whitespace-nowrap flex align-middle\"><img style=\"max-width:23px; margin-right:5px\" src=\"" + get_icon_base64("o.folder-home") + "\"/>" +
                    "<a class=\"my-auto text-blue-700\" href=\"../\">../</a></th><td>-</td><td>-</td></tr>" if dirname != "." else "",
                    ]))
            dirnames.sort()
            for subdirname in dirnames:
                f.write("<tr class=\"w-1/4 bg-white border-b hover:bg-gray-50\"><th scope=\"row\" class=\" py-2 px-2 lg:px-6 font-medium text-gray-900 whitespace-nowrap flex align-middle\"><img style=\"max-width:23px; margin-right:5px\" src=\"" + get_icon_base64("o.folder") + "\"/>" + "<a class=\"my-auto text-blue-700\" href=\"" + subdirname + "/\">" +
                        subdirname + "/</a></th><td>-</td><td>-</td></tr>\n")
            filenames.sort()
            for filename in filenames:
                path = (dirname == '.' and filename or dirname + '/' + filename)
                size = get_file_size(path, mode)
                mtime = get_file_modified_time(path, mode)
                f.write("<tr class=\"w-1/4 bg-white border-b hover:bg-gray-50\"><th scope=\"row\" class=\" py-2 px-2 lg:px-6 font-medium text-gray-900 whitespace-nowrap flex align-middle\"><img style=\"max-width:23px; margin-right:5px\" src=\"" + get_icon_base64(filename) + "\"/>" + "<a class=\"my-auto text-blue-700\" href=\"" + filename + "\">" + filename + "</a></th><td>" +
                        size + "</td><td>" + mtime + "</td></tr>\n")
            f.write("\n".join([
                get_template_foot(),
            ]))


# ---------- FETCH API ONCE PER RUN ----------

def fetch_commits_cache():
    """Fetch dists tree + latest commit date once per run"""
    global _commits_cache
    print("Fetching dists tree + commit date from GitHub...")

    # 1. get repo info -> default branch
    info = requests.get(GITHUB_API)
    if info.status_code != 200:
        _commits_cache = {}
        return
    branch = info.json().get("default_branch", "main")

    # 2. get latest commit on branch
    commit_info = requests.get(f"{GITHUB_API}/commits/{branch}")
    if commit_info.status_code != 200:
        _commits_cache = {}
        return
    commit_date = commit_info.json()["commit"]["committer"]["date"]

    # 3. get full tree
    tree_info = requests.get(f"{GITHUB_API}/git/trees/{branch}?recursive=1")
    if tree_info.status_code != 200:
        _commits_cache = {}
        return

    file_times = {}
    for item in tree_info.json().get("tree", []):
        if item["type"] == "blob":  # file
            file_times[item["path"]] = commit_date

    _commits_cache = file_times
    with open(COMMITS_JSON, "w", encoding="utf-8") as f:
        json.dump(_commits_cache, f, indent=2)
    print("Saved commits cache (this run)")


def fetch_all_releases():
    """Fetch all releases in the repo once per run"""
    print("Fetching all releases from GitHub...")
    releases = []
    page = 1
    while True:
        r = requests.get(f"{GITHUB_API}/releases?per_page=100&page={page}")
        if r.status_code != 200:
            break
        batch = r.json()
        if not batch:
            break
        releases.extend(batch)
        page += 1
    print(f"Fetched {len(releases)} releases")
    return releases


def fetch_release_cache():
    """Prepare pool release cache by matching files to tag, fallback to DEFAULT_RELEASE_TAG"""
    global _release_cache, _all_releases
    print("Building release cache for pool...")
    release_cache = {}

    # 找到默认 release
    default_release = next((r for r in _all_releases if r["tag_name"] == DEFAULT_RELEASE_TAG), None)
    default_assets = {a["name"]: a for a in default_release.get("assets", [])} if default_release else {}

    # 遍历所有 assets，按文件名取最新对应 tag
    for release in _all_releases:
        tag = release["tag_name"]
        for asset in release.get("assets", []):
            name = asset["name"]
            # 如果文件已经存在，则跳过，优先使用最新 tag
            if name in release_cache:
                continue
            release_cache[name] = {
                "size": asset["size"],
                "updated_at": asset["updated_at"],
                "tag": tag
            }

    # 回退默认 tag
    for name, asset in default_assets.items():
        if name not in release_cache:
            release_cache[name] = {
                "size": asset["size"],
                "updated_at": asset["updated_at"],
                "tag": DEFAULT_RELEASE_TAG
            }

    _release_cache = release_cache
    with open(RELEASE_JSON, "w", encoding="utf-8") as f:
        json.dump(_release_cache, f, indent=2)
    print("Saved release cache (this run)")


# ---------- HELPERS ----------

def normalize_pool_filename(name: str) -> str:
    """Normalize pool filename like JS replaceAll(/[^a-zA-Z0-9-_+%]+/g, ".")"""
    return re.sub(r"[^a-zA-Z0-9\-\_\+\%]+", ".", name)


def get_file_size(filepath, mode="other"):
    if mode == "pool" and _release_cache:
        norm_name = normalize_pool_filename(os.path.basename(filepath))
        asset = _release_cache.get(norm_name)
        if asset:
            return human_size(asset.get("size", 0))
    size = os.path.getsize(filepath)
    return human_size(size)


def get_file_modified_time(filepath, mode="other"):
    if mode == "dists" and _commits_cache:
        rel = filepath.lstrip("./")
        if rel in _commits_cache:
            return github_time_to_str(_commits_cache[rel])
    elif mode == "pool" and _release_cache:
        norm_name = normalize_pool_filename(os.path.basename(filepath))
        asset = _release_cache.get(norm_name)
        if asset:
            return github_time_to_str(asset.get("updated_at"))
    return dt.datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%Y-%m-%d %H:%M:%S UTC')


def github_time_to_str(timestr):
    try:
        t = dt.datetime.strptime(timestr, "%Y-%m-%dT%H:%M:%SZ")
        return t.strftime('%Y-%m-%d %H:%M:%S UTC')
    except Exception:
        return timestr or "-"


def human_size(size):
    if size < 1024:
        return str(size) + " B"
    elif size < 1024 * 1024:
        return str(round((size / 1024), 2)) + " KB"
    elif size < 1024 * 1024 * 1024:
        return str(round((size / 1024 / 1024), 2)) + " MB"
    else:
        return str(round((size / 1024 / 1024 / 1024), 2)) + " GB"


# ---------- TEMPLATE + ICONS ----------

def get_template_head(foldername):
    if foldername.startswith('.'):
        if not foldername.startswith('/', 1):
            return get_template_head('/' + foldername[1:])
        else:
            return get_template_head(foldername[1:])
    with open("/src/template/head.html", "r", encoding="utf-8") as file:
        head = file.read()
    head = head.replace("{{foldername}}", foldername)
    return head


def get_template_foot():
    with open("/src/template/foot.html", "r", encoding="utf-8") as file:
        foot = file.read()
    foot = foot.replace("{{buildtime}}", "at " + dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC'))
    return foot


def get_icon_base64(filename):
    with open("/src/png/" + get_icon_from_filename(filename), "rb") as file:
        return "data:image/png;base64, " + base64.b64encode(file.read()).decode('ascii')


def get_icon_from_filename(filename):
    extension = "." + filename.split(".")[-1]
    for i in data:
        if extension in i["extension"]:
            return i["icon"] + ".png"
    return "unknown.png"


if __name__ == "__main__":
    main()
