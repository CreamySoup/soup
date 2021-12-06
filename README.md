[![PEP8](https://img.shields.io/badge/code%20style-pep8-orange.svg)](https://www.python.org/dev/peps/pep-0008/)
[![MIT](https://img.shields.io/github/license/CreamySoup/soup)](LICENSE)
[![Tests](https://img.shields.io/github/workflow/status/CreamySoup/soup/CodeQL?label=tests)](.github/workflows)

# soup
CreamySoup/"Creamy SourceMod Updater" (or just **_soup_** for short), a helper script for automated SourceMod plugin updates management.

This project started as a custom utility for the Creamy Neotokyo servers (hence the name), but open sourcing and generalising it for any kind of SRCDS/SourceMod servers seemed like a good idea, in case it's helpful for someone else too.

![Diagram overview](promo/example_diagram.svg?sanitize=true)

## FAQ
### What it be?
**soup** is a Python 3 script, a SRCDS SourceMod plugin update helper, intended to be invoked periodically by an external cronjob-like automation system of one's choice.

It parses _soup recipes_, remote lists of resources to be kept up-to-date, compares those resources' contents to the target machine's local files, and re-downloads & re-compiles them if they differ. This will automatically keep such resources in-sync with their remote repository. For a SourceMod plugin, this means any new updates get automatically applied upon the next mapchange after the completion of a _soup_ update cycle.

The purpose of _soup_ is to reduce SRCDS sysop workload by making SourceMod plugin updates more automated, while also providing some granularity in terms of which plugins get updated when, with the introduction of aforementioned _recipes_ and the ability to maintain/curate them individually. For example, you could have some trusted _recipes_ auto-update their target plugins without any admin intervention, but choose to manually update more fragile or experimental plugins as required (or not at all).

## Foreword of warning
While automation is nice, a malicious actor could use this updater to execute arbitrary code on the target machine. Be sure to only use updater source lists ("recipes") that you trust 100%, or maintain your own fork of such resources where you can review and control the updates.

This warning applies not only to the _recipe_ files themselves, but also to any remote resources that those _recipes_ may point to.

## Installation

### Requirements
* Python 3

It is **highly recommended** to use the [latest release](https://github.com/CreamySoup/soup/releases/latest), and **install with [pipenv](https://github.com/pypa/pipenv)**, as described in the example below.

You'll also need to move the config.yml to its [expected config location, or set the config path environment variable](#config).

### Example scripts

#### Linux shell or Windows command prompt
```sh
# Get the files
git clone https://github.com/CreamySoup/soup && cd soup

# Get name of latest release.
git describe --tags --abbrev=0
# By default, git will clone the most recent state of the repo,
# but you can optionally pick this latest named release with:
#     git checkout <tag>
# where "<tag>" is replaced with the "git describe..." output.
# To see what's changed since the last release:
#     git log --graph --all --decorate --oneline --simplify-by-decoration

# Install/upgrade pipenv
pip3 install --user --upgrade pipenv

# Remove any previously generated Pipfiles (we generate it from requirements.txt)
rm -i Pipfile*

# Install the requirements inside a new Python (3) virtual environment
pipenv install

# If you want to symbolic link to your SRCDS from the git repo dir:
# Replace the instances of "game_dir", as defined in config.yml.
#
#   Linux symlink:
#     ln -s ./game_dir ~/path/to/srcds/game_dir
#       For example of the above, for "game_dir" equals "NeotokyoSource":
#       ln -s ./NeotokyoSource ~/path/to/srcds/NeotokyoSource
#
#   Windows junction:
#     mklink /j .\game_dir C:\path\to\srcds\game_dir
#       For example of the above, for "game_dir" equals "NeotokyoSource":
#       mklink /j .\NeotokyoSource C:\path\to\srcds\NeotokyoSource

# Run soup.py inside the created virtual env, then exit the virtual env.
# This would be the cron-scheduled command.
pipenv run python soup.py
```

#### PowerShell (Windows), fetch latest release
```ps1
# Push script location as pwd, because we do some relative paths
Push-Location $PSScriptRoot

$confirm_delete = $true # flip boolean if you like to live dangerously

$release_info_url = 'https://api.github.com/repos/CreamySoup/soup/releases/latest'

$response = Invoke-WebRequest $release_info_url |
ConvertFrom-Json |
Select zipball_url

$zip_file = 'release.zip'
$unzip_path = '.\soup'
Remove-Item $zip_file -Confirm:$confirm_delete -ErrorAction Ignore
Remove-Item $unzip_path -Confirm:$confirm_delete -Recurse -ErrorAction Ignore

Invoke-WebRequest $response.zipball_url -OutFile $zip_file
Expand-Archive -Path $zip_file -DestinationPath $unzip_path
Remove-Item $zip_file -Confirm:$confirm_delete

cd $unzip_path\*
Move-Item -Path .\* -Destination ..\
$temp_dir = Get-Location
cd ..
Remove-Item $temp_dir.Path -Confirm:$confirm_delete

Pop-Location # Pop the pwd
```

### Troubleshooting

> FileNotFoundError: \[Errno 2\] No such file or directory: \[...\]soup.py

* Try moving the config.yml to the [path specified in the error message](#os-specific-config-file-locations), or alternatively override it with the `SOUP_CFG_DIR` environment variable. More information in the [Config section](#config).

## Config
Configuration can be edited in the [_config.yml_](config.yml) file that exists in OS specific config file location, or as defined by the `SOUP_CFG_DIR` environment variable.

If you have multiple instances of the updater with their own configs, you may wish to specify the overriding environment variable for each before invoking the script. If you would like to use the soup.py script folder as the override, set the `SOUP_CFG_DIR` environment variable's value as a dot (`.`).

Please see the additional comments within the config file for more information on the options.

### OS specific config file locations:
* Linux: `~/.config/soup/config.yml`
* Windows: `%LOCALAPPDATA%\soup\soup\config.yml`

### Recipes
The most powerful config option is `recipes`, which is a list of 0 or more URLs pointing to soup.py "recipes".

A **recipe** is defined as a valid JSON document using the following structure:
```json
{
  "section": [
    {
      "key": "value",
      <...>
    },
    <...>
  ],
  <...>
}
```

where

```json
<...>
```

indicates 0 or more additional repeated elements of the same type as above.

Note that trailing commas are not allowed in the JSON syntax – it's a good idea to validate the file before pushing any recipe updates online.

#### Recipe sections

There are three valid recipe sections: _includes_, _plugins_, and _updater_. Examples follow:

* **includes** – SourceMod include files that are required by some of the plugins in the recipes' _plugins_ section. Required file extension: .inc

```json
	"includes": [
		{
			"name": "neotokyo",
			"about": "sourcemod-nt-include - The de facto NT standard include.",
			"source_url": "https://cdn.jsdelivr.net/gh/CreamySoup/sourcemod-nt-include@master/scripting/include/neotokyo.inc"
		}
	]
```

* **plugins** – SourceMod plugins that are to be kept up to date with their remote source code repositories. Required file extension: .sp

```json
	"plugins": [
		{
			"name": "nt_srs_limiter",
			"about": "SRS rof limiter timed from time of shot, inspired by Rain's nt_quickswitchlimiter.",
			"source_url": "https://cdn.jsdelivr.net/gh/CreamySoup/nt-srs-limiter@master/scripting/nt_srs_limiter.sp"
		}
	]
```

* **updater** – **Deprecated, does nothing! Do not use as this option will get removed in the future.** A self-updater section for the soup.py script contents and its _requirements.txt_. Only one section in total of this kind should exist at most in all of the recipes being used. The `url` key should be a partial URL string, which can be appended with `/soup.py` and `/requirements.txt` to fetch those resources.

```json
	"updater": [
		{
			"version": "1.3.0",
			"url": "https://cdn.jsdelivr.net/gh/CreamySoup/soup@1.3.0"
		}
	]
```

For full examples of valid recipes, see the [Neotokyo recipe](https://github.com/CreamySoup/recipe-neotokyo) repository. By default, this soup repo is configured for game "NeotokyoSource", and to use these Neotokyo default recipes.

Recipe URLs are required to use the `https://` URI scheme, in other words plaintext HTTP connections are not allowed.

If the recipe remote assets reside inside GitHub or similar repository host, it's recommended to use a CDN instead of hotlinking the repo directly for better uptime and performance. For example, using [jsDelivr](https://github.com/jsdelivr/jsdelivr), the raw GitHub URL `https://raw.githubusercontent.com/CreamySoup/recipe-neotokyo/main/neotokyo_common.json` would turn into `https://cdn.jsdelivr.net/gh/CreamySoup/recipe-neotokyo@main/neotokyo_common.json`.

## Usage
The script can be run manually with `python soup.py`, but is recommended to be automated as a [cron job](https://en.wikipedia.org/wiki/Cron) or similar.

### Which recipes to use?
If you are operating a Neotokyo SRCDS, this project offers [some recommended recipe(s) here](https://github.com/CreamySoup/recipe-neotokyo). This resource is still work-in-progress, more curated lists to be added later!

You can also host your own custom _recipes_ as you like for any SRCDS+SourceMod server setup.

## For developers
Issue tickets and pull requests are welcome! If you would like to edit the Python script(s) in this project, please note that they should remain [PEP 8](https://www.python.org/dev/peps/pep-0008/) compliant (no errors when tested using `pycodestyle`).
