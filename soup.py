#!/usr/bin/env python3

"""Helper script for automatic SourceMod/SRCDS updates.

   This Python 3 script queries online JSON lists ("RECIPES")
   of in-development SourceMod plugins, and compares their source code
   to the local gameserver's files, and automatically recompiles
   plugins where the source code has seen changes since the last run.
   It also automatically updates itself on each script run.

   This file should go to the directory path below the game root dir
   such that the relative paths below this comment make sense:
   "./<game_dir>/...", or so on.

   To fully automate the update process, this script could be
   scheduled to run for example once a day, for example with
   the command: python ./soup.py

   For more details, please refer to the documentation
   available in this project's repositories.
"""

from __future__ import print_function

from datetime import datetime
from io import BytesIO
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time
import zipfile
import urllib.request

from appdirs import user_config_dir
from strictyaml import load, Map, Str, Int, Seq

import requests
import semver


SCRIPT_NAME = "Creamy SourceMod Updater"
# Note: This plugin uses an auto-updater function reliant on version number,
# please don't manually modify this version number unless you know
# that's what you want.
SCRIPT_VERSION = semver.VersionInfo.parse("1.6.2")

CFG_DIR = os.environ.get("SOUP_CFG_DIR") or user_config_dir("soup")
with open(os.path.join(CFG_DIR, "config.yml"),
          mode="r", encoding="utf-8") as F:
    YAML_CFG_SCHEMA = Map({
        "game_dir": Str(),
        "encoding": Str(),
        "verbosity": Int(),
        "recipes": Seq(Str()),
        "gh_username": Str(),
        "gh_personal_access_token": Str(),
    })
    CFG = load(F.read(), YAML_CFG_SCHEMA)
assert CFG is not None

# Relative path to the server's "addons/sourcemod/plugins" directory.
PLUGINS_LOCAL_PATH = os.path.join(".", CFG["game_dir"].value, "addons",
                                  "sourcemod", "plugins")
# Relative path to the server's "addons/sourcemod/scripting" directory.
SCRIPTING_LOCAL_PATH = os.path.join(".", CFG["game_dir"].value, "addons",
                                    "sourcemod", "scripting")
# Relative path to the server's code includes directory.
INCLUDES_LOCAL_PATH = os.path.join(SCRIPTING_LOCAL_PATH, "include")

# Path where to find SourceMod's "spcomp" compiler binary. Should be the
# "scripting" folder by default. Note: If you're running a Windows SRCDS
# binary through Wine, you'll need to point this to the spcomp Linux binary
# of the same SM Windows version that you're running on that Wine server.
PLUGINS_COMPILER_PATH = SCRIPTING_LOCAL_PATH

assert os.path.isdir(PLUGINS_LOCAL_PATH)
assert os.path.isdir(SCRIPTING_LOCAL_PATH)
assert os.path.isdir(INCLUDES_LOCAL_PATH)
assert os.path.isdir(PLUGINS_COMPILER_PATH)

GH_API_URL = "https://api.github.com"
GH_REPO_OWNER = "CreamySoup"
GH_REPO_NAME = "soup"
GH_REPO_BASE = f"{GH_API_URL}/repos/{GH_REPO_OWNER}/{GH_REPO_NAME}"
GH_RELEASES = f"{GH_REPO_BASE}/releases/latest"
assert GH_API_URL.startswith("https://")  # require TLS


def get_url_contents(url):
    """Return contents of a HTTPS URI."""
    # Require TLS for anti-tamper.
    # Only checking URI scheme and trusting the request lib to handle the rest.
    assert url.startswith("https://")
    try:
        return urllib.request.urlopen(url).read()
    except urllib.error.HTTPError as err:
        http_code_first_digit = int(str(err.code)[:1])
        # If it's a HTTP 5XX (server side error), don't error on our side.
        if http_code_first_digit == 5:
            print(f"Got HTTP response from remote: {err.code} {err.reason}")
        else:
            raise
    return None


def print_info(msg):
    """Print info message (according to verbosity config)."""
    if CFG["verbosity"].value > 0:
        print(msg)


def print_debug(msg):
    """Print debug message (according to verbosity config)."""
    if CFG["verbosity"].value > 1:
        print(msg)


def get_file_hash(file):
    """Get a hash value for file input."""
    try:
        return get_data_hash(file.read().encode(CFG["encoding"].value))
    except UnicodeDecodeError:
        return ""


def get_data_hash(data):
    """Get a hash value for data input."""
    res = hashlib.sha256(data).hexdigest()
    assert len(res) > 0
    return res


def verify_gh_api_req(req):
    """Verify GitHub request validity."""
    try:
        req.raise_for_status()
    except requests.HTTPError:
        http_code_first_digit = int(str(req.status_code)[:1])
        # If it's a HTTP 5XX (server side error), don't error on our side.
        if http_code_first_digit == 5:
            print(f"Got HTTP response from remote: {req.status_code} {req.reason}")
            return False
        raise
    ratelimit = req.headers.get("X-RateLimit-Limit")
    ratelimit_remaining = req.headers.get("X-RateLimit-Remaining")
    ratelimit_used = req.headers.get("X-RateLimit-Used")
    ratelimit_reset = req.headers.get("X-RateLimit-Reset")
    if ratelimit is not None and ratelimit_remaining is not None and \
            ratelimit_used is not None and ratelimit_reset is not None:
        reset_mins = int(math.ceil((int(ratelimit_reset) - time.time()) / 60))
        print_info("==> Using GitHub Releases API quota – "
                   f"{ratelimit_remaining}/{ratelimit} requests remaining "
                   f"(used {ratelimit_used} requests). This rate limit resets "
                   f"in {reset_mins} minutes.")
        if int(ratelimit_remaining) <= 0:
            return False
    return True


def self_update():
    """Check for updates of this script itself."""
    print_info("=> Self-update check")

    req = requests.get(GH_RELEASES, auth=(CFG["gh_username"].value,
                                          CFG["gh_personal_access_token"].value))
    if not verify_gh_api_req(req):
        return
    json_latest = req.json()
    latest_ver = semver.VersionInfo.parse(json_latest.get("tag_name"))

    if SCRIPT_VERSION >= latest_ver:
        if SCRIPT_VERSION > latest_ver:
            print_debug(f"!! Running higher version ({SCRIPT_VERSION}) than "
                        f"release version ({latest_ver})")
        return

    print_info(f"!! Script self-update: version \"{SCRIPT_VERSION}\" --> "
               f"\"{latest_ver}\"...")

    zip_url = json_latest.get("zipball_url")

    release_commit_url = f"{GH_REPO_BASE}/git/ref/tags/{latest_ver}"

    req = requests.get(release_commit_url,
                     auth=(CFG["gh_username"].value,
                           CFG["gh_personal_access_token"].value))
    if not verify_gh_api_req(req):
        return
    release_commit_json = req.json()
    hash_cutoff_point = 7
    sha = release_commit_json["object"]["sha"][:hash_cutoff_point]

    ballname_soup = f"{GH_REPO_OWNER}-{GH_REPO_NAME}-{sha}/soup.py"
    ballname_reqs = f"{GH_REPO_OWNER}-{GH_REPO_NAME}-{sha}/requirements.txt"

    with zipfile.ZipFile(BytesIO(
            urllib.request.urlopen(zip_url).read())) as file_zip:
        realpath_self = os.path.realpath(__file__)

        with open(os.path.join(os.path.dirname(realpath_self),
                               "requirements.txt"),
                  mode="wb+") as file_reqs:
            file_reqs.seek(0)
            file_reqs.write(file_zip.open(ballname_reqs).read())
            file_reqs.truncate()
            file_reqs.flush()
            os.fsync(file_reqs.fileno())

        subprocess.run(["pipenv", "install", "-r", "requirements.txt"], check=True)

        with open(realpath_self, "wb+") as file_self:
            file_self.seek(0)
            file_self.write(file_zip.open(ballname_soup).read())
            file_self.truncate()
            file_self.flush()
            os.fsync(file_self.fileno())

    print_info("!! Self-update successful.")

    # We have modified our own source code - restart the script
    print_info("!!! Restarting soup...")
    subprocess.check_call([sys.executable, ] + sys.argv)
    sys.exit(0)


def check_for_updates(recipe):
    """Check for updates of a recipe."""
    print_info(f"=> Checking for recipe updates: {recipe}")

    update_file_contents = get_url_contents(recipe)
    if update_file_contents is None:
        return
    update_file_contents = update_file_contents.decode(CFG["encoding"].value)
    json_data = json.loads(update_file_contents)

    num_incs_processed = 0
    num_incs_updated = 0

    num_plugins_processed = 0
    num_plugins_updated = 0

    root_sections = ["includes", "plugins", "updater"]
    for root_section in root_sections:
        kv_pairs = json_data.get(root_section)
        if kv_pairs is None:
            continue
        if root_section == "updater":
            print(f"==> ! Warning: config key '{root_section}' has been "
                  "deprecated! Please update your config file.")
            continue
        for kv_pair in kv_pairs:
            if kv_pair is None:
                continue
            for _, (key, value) in enumerate(kv_pair.items(), start=1):
                if root_section == "includes":
                    if key == "name":
                        include_name = value
                        local_inc_path = os.path.join(INCLUDES_LOCAL_PATH,
                                                      (value + ".inc"))
                        inc_exists_locally = os.path.isfile(local_inc_path)
                        num_incs_processed += 1

                    print_debug(f"=> Include {key}: \"{value}\"")

                    if key == "source_url":
                        remote_inc = get_url_contents(value)
                        if remote_inc is None:
                            print("==> ! Failed to get remote include for "
                                  f"{include_name}, skipping its update for "
                                  "now.")
                            continue
                        remote_inc_hash = get_data_hash(remote_inc)
                        print_debug("==> Include code remote hash: "
                                    f"{remote_inc_hash}")

                        open_mode = "r+" if inc_exists_locally else "w"
                        f_local_inc = open(local_inc_path, mode=open_mode,
                                           newline="\n", encoding="utf-8")

                        if inc_exists_locally:
                            local_inc_hash = get_file_hash(f_local_inc)
                            print_debug("==> Include code local hash: "
                                        f"{local_inc_hash}")

                        hashes_match = (inc_exists_locally and
                                        local_inc_hash == remote_inc_hash)

                        if hashes_match:
                            print_debug("===> Source code hashes are "
                                        "identical; no need to update include "
                                        f"\"{include_name}\".")
                        else:
                            print_debug("===> Source code hashes differ; "
                                        f"updating include \"{include_name}"
                                        "\"!\n"
                                        "====> Writing source code to disk...")
                            f_local_inc.seek(0)
                            f_local_inc.write(remote_inc.decode(CFG["encoding"].value))
                            f_local_inc.truncate()
                            f_local_inc.flush()
                            os.fsync(f_local_inc)
                        f_local_inc.close()

                        if not hashes_match:
                            print_debug("====> Verifying include code "
                                        "integrity...")
                            assert os.path.isfile(local_inc_path)
                            with open(local_inc_path, mode="r",
                                      newline="\n", encoding="utf-8") as f_local_inc:
                                new_local_inc_hash = get_file_hash(f_local_inc)

                            hashes_match = \
                                (new_local_inc_hash == remote_inc_hash)

                            assert hashes_match, \
                                (f"{new_local_inc_hash} should equal "
                                 f"{remote_inc_hash}")

                            print_debug("====> Finished updating include "
                                        f"\"{include_name}\". This new "
                                        "version will be used for any future "
                                        "plugin compiles that require it.")

                            num_incs_updated += 1

                else:  # plugins
                    if key == "name":
                        plugin_name = value
                        local_source_path = os.path.join(SCRIPTING_LOCAL_PATH,
                                                         (value + ".sp"))
                        code_exists_locally = os.path.isfile(local_source_path)
                        num_plugins_processed += 1

                    print_debug(f"=> Plugin {key}: \"{value}\"")

                    if key == "source_url":
                        remote_code = get_url_contents(value)
                        if remote_code is None:
                            print("==> ! Failed to get remote code for "
                                  f"{plugin_name}, skipping its update for "
                                  "now.")
                            continue
                        remote_code_hash = get_data_hash(remote_code)
                        print_debug("==> Plugin code remote hash: "
                                    f"{remote_code_hash}")

                        open_mode = "r+" if code_exists_locally else "w"
                        f_local_src = open(local_source_path, mode=open_mode,
                                           newline="\n", encoding="utf-8")

                        if code_exists_locally:
                            local_code_hash = get_file_hash(f_local_src)
                            print_debug("==> Plugin code local hash: "
                                        f"{local_code_hash}")

                        hashes_match = (code_exists_locally and
                                        local_code_hash == remote_code_hash)

                        if hashes_match:
                            print_debug("===> Source code hashes are "
                                        "identical; no need to update plugin "
                                        f"\"{plugin_name}\".")
                        else:
                            print_debug("===> Source code hashes differ; "
                                        f"updating plugin \"{plugin_name}\"!\n"
                                        "====> Writing source code to disk...")
                            f_local_src.seek(0)
                            f_local_src.write(remote_code.decode(CFG["encoding"].value))
                            f_local_src.truncate()
                            f_local_src.flush()
                            os.fsync(f_local_src)
                        f_local_src.close()

                        if not hashes_match:
                            print_debug("====> Verifying plugin code "
                                        "integrity...")
                            assert os.path.isfile(local_source_path)

                            with open(local_source_path, mode="r",
                                      newline="\n", encoding="utf-8") as f_local_src:
                                new_local_code_hash = get_file_hash(f_local_src)

                            hashes_match = \
                                (new_local_code_hash == remote_code_hash)

                            assert hashes_match, \
                                (f"{new_local_code_hash} "
                                 f"should equal {remote_code_hash}")

                            print_debug("====> Compiling plugin "
                                        f"\"{plugin_name}\"...\n")

                            platform_is_windows = (os.name == "nt")

                            # Assuming here that any non-Windows platform is
                            # Linux, or uses a Linux style spcomp binary.
                            compiler_binary = "spcomp.exe" if \
                                platform_is_windows else "spcomp"

                            compiler_path = os.path.join(PLUGINS_COMPILER_PATH,
                                                         compiler_binary)
                            assert os.path.isfile(compiler_path)

                            subprocess.run([compiler_path, local_source_path],
                                           check=True)

                            print_debug("\n====> Installing plugin "
                                        f"\"{plugin_name}\"...")

                            plugin_binary_path = os.path.join(".",
                                                              f"{plugin_name}"
                                                              ".smx")
                            assert os.path.isfile(plugin_binary_path)

                            '''
                            print(f"""Current working directory is "
\"{os.getcwd()}\" and trying to move the .smx from \"{plugin_binary_path}\"
to {os.path.join(PLUGINS_LOCAL_PATH, (plugin_name + ".smx"))}""")
                            '''

                            shutil.move(plugin_binary_path,
                                        os.path.join(PLUGINS_LOCAL_PATH,
                                                     (plugin_name + ".smx")))

                            print_debug("====> Finished updating plugin "
                                        f"\"{plugin_name}\". It will be "
                                        "reloaded by the server on the next "
                                        "mapchange.")

                            num_plugins_updated += 1

    print_info(f"\n{num_incs_updated} of {num_incs_processed} "
               "includes checked had received new updates.\n"
               f"{num_plugins_updated} of {num_plugins_processed} "
               "plugins checked had received new updates.")


def main():
    """Entry point."""
    print_info(f"=== Running {SCRIPT_NAME}, v.{SCRIPT_VERSION} ===\n"
               f"Current time: {datetime.now()}")
    self_update()
    for recipe in CFG["recipes"].data:
        check_for_updates(recipe)


if __name__ == '__main__':
    main()
