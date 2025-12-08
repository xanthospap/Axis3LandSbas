#!/usr/bin/env python3
"""
Quote-preserving YAML config manager for SBAS using ruamel.yaml round-trip mode.
Keeps double quotes on strings and preserves formatting as much as possible.

Commands:
  init               Create config.yaml with defaults (below), keeping quotes
  set A.B.C VAL      Set/add a value at dotted path (quotes preserved for strings)
  get A.B.C          Print a value
  list               Print entire config
  wizard             Interactive prompts for all fields

Examples:
  python config_manager.py init
  python config_manager.py set sentinel.password "My$ecret!"
  python config_manager.py set stack.bbox "[34.7, 35.8, 23.1, 26.5]"
  python config_manager.py get logging.log_level
  python config_manager.py list
  python config_manager.py wizard

  python config_manager.py set project_name SBAS_NEW
  python config_manager.py set sentinel.username myuser
  python config_manager.py set sentinel.password "My$ecret!"

  python config_manager.py set sentinel.start_date 20250201
  python config_manager.py set stack.reference_date 20250112

  python config_manager.py set steps.step3_dem_creation false
  python config_manager.py set runtime.resume true

  python config_manager.py set stack.bbox "[34.70, 35.80, 23.10, 26.50]"
  python config_manager.py set mintpy.reference_lalo "[35.55, 24.01]"


"""

#!/usr/bin/env python3
# Quote/format preserving config manager (ruamel.yaml, round-trip)

import argparse, sys, shutil
from datetime import datetime
from pathlib import Path
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import DoubleQuotedScalarString as DQ

yaml = YAML(typ="rt")
yaml.preserve_quotes = True
yaml.indent(mapping=2, sequence=2, offset=2)
yaml.width = 1000

# --- represent None explicitly as 'null' instead of empty ---
from ruamel.yaml.representer import RoundTripRepresenter
def _repr_null(dumper, data):
    return dumper.represent_scalar('tag:yaml.org,2002:null', 'null')
yaml.Representer.add_representer(type(None), _repr_null)

# Fields to keep as quoted strings
FORCE_STRING = {
    "sentinel.aoi","sentinel.orbit","sentinel.start_date","sentinel.end_date",
    "sentinel.path","sentinel.frame_id",
    "dem.bbox","dem.output_dir",
    "stack.dem_file","stack.reference_date","stack.aux_cal_path",
    "logging.log_dir","logging.log_level",
    "environment.isce2_env","environment.mintpy_env","environment.isce2_root",
    "environment.topsStack_dir","environment.isce_stack_dir",
}

# Lists to keep in FLOW (inline) style
FLOW_LISTS = {"stack.bbox", "mintpy.reference_lalo"}

def backup(path: Path):
    if path.exists():
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(path, path.with_suffix(path.suffix + f".bak.{ts}"))

def load_yaml(path: Path):
    if not path.exists():
        return CommentedMap()
    with path.open("r", encoding="utf-8") as f:
        data = yaml.load(f) or CommentedMap()
        if not isinstance(data, (dict, CommentedMap)):
            raise ValueError(f"{path} must be a mapping")
        return data

def save_yaml(data, path: Path, do_backup=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    if do_backup and path.exists():
        backup(path)
    # enforce flow style + null spelling just before dump
    _apply_flow_styles(data)
    with path.open("w", encoding="utf-8") as f:
        yaml.dump(data, f)

def _apply_flow_styles(d, prefix=""):
    """Ensure specific lists are written inline (flow) and strings stay quoted."""
    if isinstance(d, (dict, CommentedMap)):
        for k, v in d.items():
            dotted = f"{prefix}.{k}" if prefix else str(k)
            if dotted in FLOW_LISTS and isinstance(v, list):
                # convert to CommentedSeq and mark as flow
                if not isinstance(v, CommentedSeq):
                    cs = CommentedSeq(v)
                else:
                    cs = v
                cs.fa.set_flow_style()  # make inline: [a, b]
                d[k] = cs
            elif isinstance(v, (dict, CommentedMap, list, CommentedSeq)):
                _apply_flow_styles(v, dotted)
            # quote forced strings
            if dotted in FORCE_STRING and isinstance(d[k], str) and not isinstance(d[k], DQ):
                d[k] = DQ(d[k])
    elif isinstance(d, (list, CommentedSeq)):
        for i, v in enumerate(d):
            _apply_flow_styles(v, prefix)

def ensure_branch(root: CommentedMap, dotted: str):
    parts = dotted.split(".")[:-1]
    cur = root
    for p in parts:
        if p not in cur or not isinstance(cur[p], (dict, CommentedMap)):
            cur[p] = CommentedMap()
        cur = cur[p]
    return cur

def parse_cli_value(dotted: str, raw: str):
    # forced strings
    if dotted in FORCE_STRING:
        return DQ(raw)
    t = raw.strip().lower()
    if t == "true":  return True
    if t == "false": return False
    if t == "null":  return None
    # try YAML for lists/dicts/numbers
    try:
        parsed = yaml.load(raw)
        if isinstance(parsed, str):
            return DQ(parsed)
        if isinstance(parsed, list):
            seq = CommentedSeq(parsed)
            # if it’s one of our flow lists, mark it flow
            if dotted in FLOW_LISTS:
                seq.fa.set_flow_style()
            return seq
        return parsed
    except Exception:
        return DQ(raw)

def set_path(root: CommentedMap, dotted: str, value):
    parent = ensure_branch(root, dotted)
    key = dotted.split(".")[-1]
    parent[key] = value

def get_path(d: dict, dotted: str):
    cur = d
    for p in dotted.split("."):
        if not isinstance(cur, (dict, CommentedMap)) or p not in cur:
            raise KeyError(dotted)
        cur = cur[p]
    return cur

# ------- Defaults (kept quoted; lists flow) -------
def defaults():
    d = CommentedMap()
    d["project_name"] = "SBAS_SAT4GAIA"
    d["working_dir"] = "./"
    d["steps"] = CommentedMap({
        "step1_download_sentinel": True,
        "step2_download_orbits": True,
        "step3_dem_creation": True,
        "step4_stack_interferograms": True,
        "step5_run_stack": True,
        "step6_run_mintpy": True,
    })
    d["sentinel"] = CommentedMap({
        "aoi": DQ("24.07,35.37,24.22,35.27"),
        "orbit": DQ("DESCENDING"),
        "start_date": DQ("20250101"),
        "end_date": DQ("20250301"),
        "path": DQ(""),
        "frame_id": DQ(""),
        "username": "EARTHDATA_username",
        "password": "EARTHDATA_password",
    })
    d["dem"] = CommentedMap({
        "bbox": DQ("34 36 23 27"),
        "output_dir": DQ("DEM"),
    })
    d["stack"] = CommentedMap({
        "bbox": CommentedSeq([34.56, 35.89, 23.0, 26.68]),
        "reference_date": DQ("20250112"),
        "aux_cal_path": DQ("/home/sbas/aux_cal"),
        "config": None,  # will be emitted as 'null'
    })
    # make these two lists flow (inline)
    d["stack"]["bbox"].fa.set_flow_style()
    d["mintpy"] = CommentedMap({
        "reference_lalo": CommentedSeq([35.5, 24.02]),
    })
    d["mintpy"]["reference_lalo"].fa.set_flow_style()
    d["logging"] = CommentedMap({
        "log_dir": DQ("logs"),
        "log_level": DQ("INFO"),
    })
    d["environment"] = CommentedMap({
        #"isce2_env": DQ("isce2"),
        #"mintpy_env": DQ("mintpy"),
        "isce2_env": DQ("base"),  # micromamba env name
        "mintpy_env": DQ("base"),
        #"topsStack_dir": DQ("/opt/isce2_tools"),
        #"isce_stack_dir": DQ("/usr/lib/python3.8/dist-packages/isce2/applications"),
        #"conda_python_path": DQ("/opt/miniconda/envs/isce2/bin/python"),
        #"conda_env_path": DQ("/opt/miniconda/envs/isce2/bin"),
        "topsStack_dir": DQ("/opt/conda/share/isce2/topsStack"),
        "isce_stack_dir": DQ("/opt/conda/share/isce2"),
        "conda_python_path": DQ("/opt/conda/bin/python"),
        "conda_env_path": DQ("/opt/conda/bin"),
    })
    d["runtime"] = CommentedMap({
        "resume": False,
        "dry_run": False,
        "start_from_step": None,  # will be 'null'
    })
    return d
# ---------------------------------------------------

def cmd_init(args):
    cfg = Path(args.path)
    if cfg.exists() and not args.force:
        print(f"[!] {cfg} exists. Use --force to overwrite, or use `set` to modify.")
        return 1
    if args.from_template:
        tpl = Path(args.from_template)
        if not tpl.exists():
            print(f"[!] Template not found: {tpl}")
            return 1
        data = load_yaml(tpl)
    else:
        data = defaults()
    save_yaml(data, cfg, do_backup=False)
    print(f"[✓] Wrote {cfg}")
    return 0

def cmd_set(args):
    cfg = Path(args.path)
    data = load_yaml(cfg)
    val = parse_cli_value(args.dotted, args.value)
    set_path(data, args.dotted, val)
    save_yaml(data, cfg)
    print(f"[✓] Set {args.dotted} = {args.value}")
    return 0

def cmd_get(args):
    data = load_yaml(Path(args.path))
    try:
        val = get_path(data, args.dotted)
    except KeyError:
        print(f"[!] {args.dotted} not found"); return 1
    yaml.dump(val, sys.stdout); return 0

def cmd_list(args):
    data = load_yaml(Path(args.path))
    yaml.dump(data, sys.stdout); return 0

def main():
    ap = argparse.ArgumentParser(description="Quote/format preserving config manager")
    ap.add_argument("--path", default="config.yaml", help="Config file path")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp_init = sub.add_parser("init", help="Create config (optionally from template)")
    sp_init.add_argument("--force", action="store_true")
    sp_init.add_argument("--from", dest="from_template", help="Clone this YAML exactly")

    sp_set = sub.add_parser("set", help="Set/add value: A.B.C value")
    sp_set.add_argument("dotted"); sp_set.add_argument("value")

    sp_get = sub.add_parser("get", help="Get value: A.B.C")
    sp_get.add_argument("dotted")

    sub.add_parser("list", help="Print entire config")

    args = ap.parse_args()
    if args.cmd == "init": sys.exit(cmd_init(args))
    if args.cmd == "set":  sys.exit(cmd_set(args))
    if args.cmd == "get":  sys.exit(cmd_get(args))
    if args.cmd == "list": sys.exit(cmd_list(args))

if __name__ == "__main__":
    main()
