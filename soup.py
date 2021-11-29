#!/usr/bin/env python3

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

from appdirs import *
from strictyaml import load, Map, Str, Int, Seq, YAMLError

import requests
import semver

# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
#                                                                             #
# soup                                                                        #
#                                                                             #
# CreamySoup/"Creamy SourceMod Updater", a helper script for automatic       #
# SourceMod plugin updates for in-active-development plugins.               #
#                                                                          #
# This Python 3 script queries online JSON lists ("RECIPES")              #
# of in-development SourceMod plugins, and compares their source code    #
# to the local gameserver's files, and automatically recompiles         #
# plugins where the source code has seen changes since the last run.   #
# It also automatically updates itself on each script run.            #
#                                                                    #
# This file should go to the directory path below the game root dir #
# such that the relative paths below this comment make sense:      #
#  "./<game_dir>/...", or so on.                                  #
#                                                                #
# To fully automate the update process, this script could be    #
# scheduled to run for example once a day, for example with    #
# the command:                                                #
#  "python ./soup.py"                                        #
#                                                           #
# For more details, please refer to the documentation      #
# available in this project's repositories.               #
#                                                        #
# # # # # # # # # # # # # # # # # # # # # # # # # # # # #

CFG_DIR = os.environ.get("SOUP_CFG_DIR") or user_config_dir("soup")
with open(os.path.join(CFG_DIR, "config.yml"), "r") as f:
    YAML_CFG_SCHEMA = Map({
        "game_dir": Str(),
        "encoding": Str(),
        "verbosity": Int(),
        "recipes": Seq(Str()),
        "gh_username": Str(),
        "gh_personal_access_token": Str(),
    })
    CFG = load(f.read(), YAML_CFG_SCHEMA)
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

SCRIPT_NAME = "Creamy SourceMod Updater"
SCRIPT_VERSION = semver.VersionInfo.parse("1.5.0")


def get_url_contents(url):
    # Require TLS for anti-tamper.
    # Only checking URI scheme and trusting the request lib to handle the rest.
    assert url.startswith("https://")
    try:
        return urllib.request.urlopen(url).read()
    except urllib.error.HTTPError as e:
        http_code_first_digit = int(str(e.code)[:1])
        # If it's a HTTP 5XX (server side error), don't error on our side.
        if http_code_first_digit == 5:
            print(f"Got HTTP response from remote: {e.code} {e.reason}")
        else:
            raise
    return None


def print_info(msg):
    if CFG["verbosity"].value > 0:
        print(msg)


def print_debug(msg):
    if CFG["verbosity"].value > 1:
        print(msg)


def get_file_hash(file):
    return get_data_hash(file.read().encode(CFG["encoding"].value))


def get_data_hash(data):
    res = hashlib.sha256(data).hexdigest()
    assert len(res) > 0
    return res


def verify_gh_api_req(r):
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        http_code_first_digit = int(str(r.status_code)[:1])
        # If it's a HTTP 5XX (server side error), don't error on our side.
        if http_code_first_digit == 5:
            print(f"Got HTTP response from remote: {r.status_code} {r.reason}")
            return False
        else:
            raise
    ratelimit = r.headers.get("X-RateLimit-Limit")
    ratelimit_remaining = r.headers.get("X-RateLimit-Remaining")
    ratelimit_used = r.headers.get("X-RateLimit-Used")
    ratelimit_reset = r.headers.get("X-RateLimit-Reset")
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


# Check for updates of this script itself
def self_update():
    print_info(f"=> Self-update check")

    r = requests.get(GH_RELEASES, auth=(CFG["gh_username"].value,
                                        CFG["gh_personal_access_token"].value))
    if not verify_gh_api_req(r):
        return
    json_latest = r.json()
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

    r = requests.get(release_commit_url,
                     auth=(CFG["gh_username"].value,
                           CFG["gh_personal_access_token"].value))
    if not verify_gh_api_req(r):
        return
    release_commit_json = r.json()
    hash_cutoff_point = 7
    sha = release_commit_json["object"]["sha"][:hash_cutoff_point]

    ballname_soup = f"{GH_REPO_OWNER}-{GH_REPO_NAME}-{sha}/soup.py"
    ballname_reqs = f"{GH_REPO_OWNER}-{GH_REPO_NAME}-{sha}/requirements.txt"

    with zipfile.ZipFile(BytesIO(urllib.request.urlopen(zip_url).read())) as z:
        realpath = os.path.realpath(__file__)

        with open(os.path.join(os.path.dirname(realpath), "requirements.txt"),
                  "wb+") as f:
            f.seek(0)
            f.write(z.open(ballname_reqs).read())
            f.truncate()
            f.flush()
            os.fsync(f.fileno())

        subprocess.run("pipenv install -r requirements.txt").check_returncode()

        with open(realpath, "wb+") as f:
            f.seek(0)
            f.write(z.open(ballname_soup).read())
            f.truncate()
            f.flush()
            os.fsync(f.fileno())

    print_info("!! Self-update successful.")

    # We have modified our own source code - restart the script
    print_info("!!! Restarting soup...")
    subprocess.check_call([sys.executable, ] + sys.argv)
    sys.exit(0)


def check_for_updates(recipe):
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
        kvs = json_data.get(root_section)
        if kvs is None:
            continue
        if root_section == "updater":
            print(f"==> ! Warning: config key '{root_section}' has been "
                  "deprecated! Please update your config file.")
            continue
        for kv in kvs:
            if kv is None:
                continue
            for index, (key, value) in enumerate(kv.items(), start=1):
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
                        f = open(local_inc_path, open_mode, newline="\n")

                        if inc_exists_locally:
                            local_inc_hash = get_file_hash(f)
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
                            f.seek(0)
                            f.write(remote_inc.decode(CFG["encoding"].value))
                            f.truncate()
                            f.flush()
                            os.fsync(f)
                        f.close()

                        if not hashes_match:
                            print_debug("====> Verifying include code "
                                        "integrity...")
                            assert os.path.isfile(local_inc_path)
                            with open(local_inc_path, "r", newline="\n") as f:
                                new_local_inc_hash = get_file_hash(f)

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
                        f = open(local_source_path, open_mode, newline="\n")

                        if code_exists_locally:
                            local_code_hash = get_file_hash(f)
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
                            f.seek(0)
                            f.write(remote_code.decode(CFG["encoding"].value))
                            f.truncate()
                            f.flush()
                            os.fsync(f)
                        f.close()

                        if not hashes_match:
                            print_debug("====> Verifying plugin code "
                                        "integrity...")
                            assert os.path.isfile(local_source_path)

                            with open(local_source_path, "r",
                                      newline="\n") as f:
                                new_local_code_hash = get_file_hash(f)

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

                            subprocess.run(
                                [compiler_path,
                                 local_source_path]).check_returncode()

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
    print_info(f"=== Running {SCRIPT_NAME}, v.{SCRIPT_VERSION} ===\n"
               f"Current time: {datetime.now()}")
    self_update()
    for recipe in CFG["recipes"].data:
        check_for_updates(recipe)


if __name__ == '__main__':
    main()
