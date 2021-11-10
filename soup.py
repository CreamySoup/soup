#!/usr/bin/env python3

from __future__ import print_function

from datetime import datetime
import hashlib
import json
import os
import shutil
import subprocess
import urllib.request

import yaml

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

CFG_FILE = open("config.yml")
CFG = yaml.safe_load(CFG_FILE)

# Relative path to the server's "addons/sourcemod/plugins" directory.
PLUGINS_LOCAL_PATH = os.path.join(".", CFG["game_dir"], "addons",
                                  "sourcemod", "plugins")
# Relative path to the server's "addons/sourcemod/scripting" directory.
SCRIPTING_LOCAL_PATH = os.path.join(".", CFG["game_dir"], "addons",
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

SCRIPT_NAME = "Creamy SourceMod Updater"
SCRIPT_VERSION = "1.0.0"


def get_url_contents(url):
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
    if CFG["verbosity"] > 0:
        print(msg)


def print_debug(msg):
    if CFG["verbosity"] > 1:
        print(msg)


def recursive_iter(obj, keys=()):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from recursive_iter(v, keys + (k,))
    elif any(isinstance(obj, t) for t in (list, tuple)):
        for idx, item in enumerate(obj):
            yield from recursive_iter(item, keys + (idx,))
    else:
        yield keys, obj


def get_file_hash(file):
    return get_data_hash(file.read().encode(CFG["encoding"]))


def get_data_hash(data):
    res = hashlib.sha256(data).hexdigest()
    assert len(res) > 0
    return res


# Check for updates of this script itself
def self_update(new_version, new_version_url):
    assert new_version is not None and new_version_url is not None
    new_script_data = get_url_contents(new_version_url)

    # If we got None and haven't yet raised an error, it was a remote server
    # error unrelated to us. Just return early and try again some other time.
    if new_script_data is None:
        return

    is_pending_update = False

    # For compat with some Windows tools. Can use plain \n if working on this
    # file on purely on Unix. This matters here, because we're hashing the file
    # contents to check for updates.
    this_newline = "\r\n"

    with open(os.path.realpath(__file__), "r", newline=this_newline) as f:
        current_script_hash = get_file_hash(f)
        assert current_script_hash is not None
        new_script_hash = get_data_hash(new_script_data)
        is_pending_update = current_script_hash != new_script_hash

    if not is_pending_update:
        return

    # Do the actual file update here
    with open(os.path.realpath(__file__), "w+", newline="\n") as f:
        print_info(f"!! Script self-update: version \"{SCRIPT_VERSION}\" --> "
                   f"\"{new_version}\"...")
        f.seek(0)
        f.write(new_script_data.decode(CFG["encoding"]))
        f.truncate()
        f.flush()
        os.fsync(f)

    # Re-open the file after the update to confirm it was written successfully
    with open(os.path.realpath(__file__), "r", newline=this_newline) as f:
        current_script_hash = get_file_hash(f)
        assert current_script_hash is not None
        assert current_script_hash == new_script_hash
        print_info("!! Self-update successful.")


def check_for_updates(recipe):
    print_info(f"=> Checking for updates: {recipe}")

    update_file_contents = get_url_contents(recipe)
    if update_file_contents is None:
        return
    update_file_contents = update_file_contents.decode(CFG["encoding"])
    json_data = json.loads(update_file_contents)

    num_incs_processed = 0
    num_incs_updated = 0

    num_plugins_processed = 0
    num_plugins_updated = 0

    for k, value in recursive_iter(json_data):
        root_section = k[0]
        index = k[1]
        key = k[2]

        assert root_section == "updater" \
            or root_section == "includes" \
            or root_section == "plugins"

        if root_section == "updater":
            assert key == "version" or key == "url"

            if key == "version":
                new_version = value
            elif key == "url":
                new_version_url = value
                self_update(new_version, new_version_url)

        elif root_section == "includes":
            if key == "name":
                include_name = value
                print_debug("- - - - - - - - - - - - - - - - - - - -\n"
                            f"* Processing include # {index + 1}.")
                local_inc_path = os.path.join(INCLUDES_LOCAL_PATH,
                                              (value + ".inc"))
                inc_exists_locally = os.path.isfile(local_inc_path)
                num_incs_processed += 1

            print_debug(f"=> Include {key}: \"{value}\"")

            if key == "source_url":
                remote_inc = get_url_contents(value)
                if remote_inc is None:
                    print("==> ! Failed to get remote include for "
                          f"{include_name}, skipping its update for now.")
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
                    print_debug("===> Source code hashes are identical; "
                                "no need to update include "
                                f"\"{include_name}\".")
                else:
                    print_debug("===> Source code hashes differ; updating "
                                f"include \"{include_name}\"!\n"
                                "====> Writing source code to disk...")
                    f.seek(0)
                    f.write(remote_inc.decode(CFG["encoding"]))
                    f.truncate()
                    f.flush()
                    os.fsync(f)
                f.close()

                if not hashes_match:
                    print_debug("====> Verifying include code integrity...")
                    assert os.path.isfile(local_inc_path)
                    with open(local_inc_path, "r", newline="\n") as f:
                        new_local_inc_hash = get_file_hash(f)
                    hashes_match = (new_local_inc_hash == remote_inc_hash)
                    assert hashes_match, (new_local_inc_hash +
                                          " should equal " + remote_inc_hash)

                    print_debug("====> Finished updating include "
                                f"\"{include_name}\". This new version will "
                                "be used for any future plugin compiles that "
                                "require it.")

                    num_incs_updated += 1

        else:  # plugins
            if key == "name":
                plugin_name = value
                print_debug("- - - - - - - - - - - - - - - - - - - -"
                            f"* Processing plugin # {index + 1}.")
                local_source_path = os.path.join(SCRIPTING_LOCAL_PATH,
                                                 (value + ".sp"))
                code_exists_locally = os.path.isfile(local_source_path)
                num_plugins_processed += 1

            print_debug(f"=> Plugin {key}: \"{value}\"")

            if key == "source_url":
                remote_code = get_url_contents(value)
                if remote_code is None:
                    print("==> ! Failed to get remote code for "
                          f"{plugin_name}, skipping its update for now.")
                    continue
                remote_code_hash = get_data_hash(remote_code)
                print_debug(f"==> Plugin code remote hash: {remote_code_hash}")

                open_mode = "r+" if code_exists_locally else "w"
                f = open(local_source_path, open_mode, newline="\n")

                if code_exists_locally:
                    local_code_hash = get_file_hash(f)
                    print_debug("==> Plugin code local hash: "
                                f"{local_code_hash}")

                hashes_match = (code_exists_locally and
                                local_code_hash == remote_code_hash)

                if hashes_match:
                    print_debug("===> Source code hashes are identical; "
                                f"no need to update plugin \"{plugin_name}\".")
                else:
                    print_debug("===> Source code hashes differ; updating "
                                f"plugin \"{plugin_name}\"!\n"
                                "====> Writing source code to disk...")
                    f.seek(0)
                    f.write(remote_code.decode(CFG["encoding"]))
                    f.truncate()
                    f.flush()
                    os.fsync(f)
                f.close()

                if not hashes_match:
                    print_debug("====> Verifying plugin code integrity...")
                    assert os.path.isfile(local_source_path)
                    with open(local_source_path, "r", newline="\n") as f:
                        new_local_code_hash = get_file_hash(f)
                    hashes_match = (new_local_code_hash == remote_code_hash)
                    assert hashes_match, (new_local_code_hash +
                                          " should equal " + remote_code_hash)

                    print_debug("====> Compiling plugin "
                                f"\"{plugin_name}\"...\n")

                    platform_is_windows = (os.name == "nt")

                    # Assuming here that any non-Windows platform is Linux,
                    # or uses a Linux style spcomp binary.
                    compiler_binary = "spcomp.exe" if platform_is_windows \
                        else "spcomp"

                    compiler_path = os.path.join(PLUGINS_COMPILER_PATH,
                                                 compiler_binary)
                    assert os.path.isfile(compiler_path)
                    subprocess.run(
                        [compiler_path, local_source_path]).check_returncode()

                    print_debug(f"\n====> Installing plugin \"{plugin_name}\""
                                "...")

                    plugin_binary_path = os.path.join(".",
                                                      (plugin_name + ".smx"))
                    assert os.path.isfile(plugin_binary_path)

                    '''
                    print(f"""Current working directory is \"{os.getcwd()}\"
and trying to move the .smx from \"{plugin_binary_path}\" to
{os.path.join(PLUGINS_LOCAL_PATH, (plugin_name + ".smx"))}""")
                    '''

                    shutil.move(plugin_binary_path,
                                os.path.join(PLUGINS_LOCAL_PATH,
                                             (plugin_name + ".smx")))

                    print_debug("====> Finished updating plugin "
                                f"\"{plugin_name}\". It will be reloaded by "
                                "the server on the next mapchange.")

                    num_plugins_updated += 1

    print_info(f"\n{num_incs_updated} of {num_incs_processed} includes "
               "checked had received new updates.\n"
               f"{num_plugins_updated} of {num_plugins_processed} plugins "
               "checked had received new updates.")


def main():
    print_info(f"=== Running {SCRIPT_NAME}, v.{SCRIPT_VERSION} ===\n"
               f"Current time: {datetime.now()}")
    for recipe in CFG["recipes"]:
        check_for_updates(recipe)


if __name__ == '__main__':
    main()

CFG_FILE.close()
