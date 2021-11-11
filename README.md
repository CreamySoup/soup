# soup
CreamySoup/"Creamy SourceMod Updater" (or just **_soup_** for short), a helper script for automated SourceMod plugin updates management.

This project started as a custom utility for the Creamy Neotokyo servers (hence the name), but open sourcing and generalising it for any kind of SRCDS/SourceMod servers seemed like a good idea, in case it's helpful for someone else too.

![alt text](promo/example_diagram.svg)

## FAQ
### What it be?
**soup** is a Python 3 script, a SRCDS SourceMod plugin update helper, intended to be invoked periodically by an external cronjob-like automation system.

It parses _soup recipes_, remote lists of resources to be kept up-to-date, compares those resources' contents to the target machine's local files, and re-downloads & re-compiles them if they differ. This will automatically keep such resources in-sync with their remote repository. For a SourceMod plugin, this means any new updates get automatically applied upon the next mapchange after the completion of a soup update cycle.

The purpose of _soup_ is to reduce admin workload by making SourceMod plugin updates more automated, while also providing some granularity in terms of which plugins get updated when, with the introduction of maintained/curated _recipes_. For example, you can have some trusted _recipes_ auto-update their target plugins without any admin intervention, but choose to manually update more fragile or experimental plugins as required (or not at all).

### Which recipes to use?
You should always use the [default self-updater recipe](recipe_selfupdate.json) to keep the _soup_ script itself updated.

If you are operating a Neotokyo SRCDS, this project offers [some recommended recipe(s) here](https://github.com/CreamySoup/recipe-neotokyo). This resource is still work-in-progress, more curated lists to be added later!

You can also host your own custom _recipes_ as you like for any SRCDS+SourceMod server setup.

## Foreword of warning
While automation is nice, a malicious actor could use this updater to execute arbitrary code on the target machine. Be sure to only use updater source lists ("recipes") that you trust 100%, or maintain your own fork of such resources where you can review and control the updates.

## Installation
Recommended to [install with pip](https://pip.pypa.io/en/stable/cli/pip_install/), using the _requirements.txt_ file.

You should also consider using a [virtual environment](https://docs.python.org/3/library/venv.html) to isolate any Python dependencies from the rest of the system (although if you go this route, any cron job or similar automation should also run in that venv to have access to those deps).

### Requirements
* Python 3

## Config
Configuration can be edited in the [_config.yml_](config.yml) file that exists in the same dir as the Python script itself.
Please see the additional comments within the config file for more information on the options.

### Recipes
The most powerful config option is `recipes`, which is a list of 0 or more URLs pointing to soup.py "recipes".

A recipe is defined as a valid JSON document using the following structure:
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

There are three valid recipe sections: _updater_, _includes_, and _plugins_. Examples follow:

* **updater** – A self-updater section for the soup.py script contents. Only one section in total of this kind should exist at most in all of the recipes being used.

```json
	"updater": [
		{
			"version": "1.0.0",
			"url": "https://raw.githubusercontent.com/CreamySoup/soup/main/soup.py"
		}
	]
```

* **includes** – SourceMod include files that are required by some of the plugins in the recipes' _plugins_ section. Required file extension: .inc

```json
	"includes": [
		{
			"name": "neotokyo",
			"about": "sourcemod-nt-include - The de facto NT standard include.",
			"source_url": "https://raw.githubusercontent.com/CreamySoup/sourcemod-nt-include/master/scripting/include/neotokyo.inc"
		}
	]
```

* **plugins** – SourceMod plugins that are to be kept up to date with their remote source code repositories. Required file extension: .sp

```json
	"plugins": [
		{
			"name": "nt_srs_limiter",
			"about": "SRS rof limiter timed from time of shot, inspired by Rain's nt_quickswitchlimiter.",
			"source_url": "https://raw.githubusercontent.com/CreamySoup/nt-srs-limiter/master/scripting/nt_srs_limiter.sp"
		}
	]
```

For full examples of valid recipes, see the [self updater](recipe_selfupdate.json) in this repo, and the [Neotokyo recipe](https://github.com/CreamySoup/recipe-neotokyo) repository. By default, this repo is configured for game "NeotokyoSource", and to use these Neotokyo default recipes.

## Usage
The script can by run manually with `python soup.py`, but is recommended to be automated as a [cron job](https://en.wikipedia.org/wiki/Cron) or similar.

## For developers
The _soup.py_ Python script should be [PEP 8](https://www.python.org/dev/peps/pep-0008/) compliant (tested using `pycodestyle`).
