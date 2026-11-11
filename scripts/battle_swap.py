import re
import sys
import json
import random
import shutil
from pathlib import Path

import eb_randomizer as base

# ==================== CONFIGURATION ====================
# Les réglages (chemins, base de données, graine, SWAP_SELECTION, SWAP_MAX_HP_RATIO,
# SWAP_SCALE_STATS) se modifient dans eb_randomizer.py.
MIN_CANDIDATES = 8
LANGUAGES = ("us", "uk", "jp", "es", "fr", "gr", "it")
SWAP_LOG_FILE = Path("swap_log.json")
# =======================================================

DEFAULT_SETTINGS = {
    "SWAP_SELECTION": "wide",
    "SWAP_LEVEL_WINDOW": 12,
    "SWAP_WIDE_HP_RATIO": 15.0,
    "SWAP_MAX_HP_RATIO": 40.0,
    "SWAP_SCALE_STATS": True,
    "SWAP_EXTRA_TYPES": 0,
}


def setting(name: str, default=None):
    return getattr(base, name, DEFAULT_SETTINGS.get(name, default) if default is None else default)


SCENE_REGEX = re.compile(r"battlemap/battlescene/(evt_battle_[^/]+)/(\d+)\.raw17\.bytes$", re.IGNORECASE)
RAW16_REGEX = re.compile(r"battlemap/battlescene/(evt_battle_[^/]+)/dbfile0000\.raw16\.bytes$", re.IGNORECASE)
SCRIPT_REGEX = re.compile(r"eventbinary/battle/([a-z]+)/(evt_battle_[^/]+)\.eb\.bytes$", re.IGNORECASE)
TEXT_REGEX = re.compile(r"embeddedasset/text/([a-z]+)/battle/(\d+)(?:\.mes)?$", re.IGNORECASE)

SCENE_DIR = Path("StreamingAssets/Assets/Resources/BattleMap/BattleScene")
SCRIPT_DIR = Path("StreamingAssets/Assets/Resources/CommonAsset/EventEngine/EventBinary/Battle")
TEXT_DIR = Path("FF9_Data/EmbeddedAsset/Text")


def find_manager_file(data_dir: Path):
    for name in ("globalgamemanagers", "mainData"):
        candidate = data_dir / name
        if candidate.exists():
            return candidate
    return None


# ==================== LECTURE DES ARCHIVES DU JEU ====================
# Les combats sont répartis dans trois endroits : p0data2.bin (scène et données
# du combat), p0data7.bin (script de combat, par langue) et resources.assets
# (textes de combat, par langue).
def raw_bytes(ptr) -> bytes:
    asset = ptr.read()
    content = asset.m_Script
    return content.encode("utf-8", "surrogateescape") if isinstance(content, str) else bytes(content)


def read_archives(game_dir: Path, needed_ids):
    import UnityPy
    data = {"raw17": {}, "folder_of": {}, "folder_ids": {}, "raw16": {}, "script": {}, "text": {}, "envs": []}

    p0data2 = game_dir / "StreamingAssets" / "p0data2.bin"
    print(f"   Lecture de '{p0data2.name}'...")
    env = UnityPy.load(str(p0data2))
    data["envs"].append(env)
    for path, ptr in env.container.items():
        norm = path.replace("\\", "/")
        m = SCENE_REGEX.search(norm)
        if m:
            folder = m.group(1).lower()
            battle_id = int(m.group(2))
            data["folder_ids"].setdefault(folder, set()).add(battle_id)
            if battle_id in needed_ids:
                data["folder_of"][battle_id] = folder
                data["raw17"][battle_id] = raw_bytes(ptr)
            continue
        m = RAW16_REGEX.search(norm)
        if m:
            data["raw16"][m.group(1).lower()] = ptr

    p0data7 = game_dir / "StreamingAssets" / "p0data7.bin"
    print(f"   Lecture de '{p0data7.name}'...")
    env = UnityPy.load(str(p0data7))
    data["envs"].append(env)
    for path, ptr in env.container.items():
        m = SCRIPT_REGEX.search(path.replace("\\", "/"))
        if m and m.group(1).lower() in LANGUAGES:
            data["script"][(m.group(1).lower(), m.group(2).lower())] = ptr

    data_dir = None
    for sub in ("x64", "x86"):
        if (game_dir / sub / "FF9_Data" / "resources.assets").exists():
            data_dir = game_dir / sub / "FF9_Data"
            break
    if data_dir is None:
        raise FileNotFoundError("resources.assets introuvable (x64 ou x86 / FF9_Data)")

    entries = []
    manager_file = find_manager_file(data_dir)
    print(f"   Lecture de '{manager_file.name if manager_file else 'globalgamemanagers/mainData'}' (liste des chemins)...")
    if manager_file is not None:
        env_manager = UnityPy.load(str(manager_file))
        data["envs"].append(env_manager)
        for obj in env_manager.objects:
            if obj.type.name == "ResourceManager":
                for name, ptr in obj.read().m_Container:
                    entries.append((str(name), ptr.path_id))
    print(f"   Chemins de ressources lus : {len(entries)}")

    print("   Lecture de 'resources.assets' (textes)...")
    env_resources = UnityPy.load(str(data_dir / "resources.assets"))
    data["envs"].append(env_resources)
    text_objects = {obj.path_id: obj for obj in env_resources.objects if obj.type.name == "TextAsset"}
    for name, path_id in entries:
        m = TEXT_REGEX.search(name.replace("\\", "/"))
        if m and m.group(1).lower() in LANGUAGES and int(m.group(2)) in needed_ids and path_id in text_objects:
            data["text"][(m.group(1).lower(), int(m.group(2)))] = text_objects[path_id]
    return data


# ==================== DIAGNOSTIC DES TEXTES ====================
def diagnose_texts(game_dir: Path) -> None:
    import UnityPy
    data_dir = None
    for sub in ("x64", "x86"):
        if (game_dir / sub / "FF9_Data" / "resources.assets").exists():
            data_dir = game_dir / sub / "FF9_Data"
            break
    if data_dir is None:
        print("resources.assets introuvable")
        return
    print(f"Dossier : {data_dir}")
    print("Fichiers principaux du dossier :")
    for item in sorted(data_dir.iterdir()):
        if item.is_file() and (item.name.startswith(("globalgamemanagers", "resources", "unity_builtin", "mainData")) or item.suffix == ""):
            print(f"   {item.name} ({item.stat().st_size // 1024} Ko)")

    manager_file = find_manager_file(data_dir)
    if manager_file is not None:
        env = UnityPy.load(str(manager_file))
        counts = {}
        managers = []
        for obj in env.objects:
            counts[obj.type.name] = counts.get(obj.type.name, 0) + 1
            if obj.type.name == "ResourceManager":
                managers.append(obj)
        print(f"{manager_file.name} : fichiers chargés {len(env.files)}, types {sorted(counts.items(), key=lambda kv: -kv[1])[:6]}")
        for manager in managers:
            container = manager.read().m_Container
            names = [str(name) for name, _ in container]
            battle = [n for n in names if "battle" in n.lower()]
            print(f"   ResourceManager : {len(names)} entrées, dont {len(battle)} contenant 'battle'")
            for sample in (battle or names)[:10]:
                print(f"      {sample}")
    else:
        print("globalgamemanagers et mainData : fichiers absents")


# ==================== NOMBRE D'ENNEMIS ET DE TYPES PAR GROUPE ====================
# Chaque scène de combat contient plusieurs "groupes" (variantes d'une même
# rencontre) avec un pourcentage de chance, un nombre d'ennemis et un nombre
# de types d'ennemis (typ_count).
PATTERN_SIZE = 56
PUT_OFFSET = 8
PUT_SIZE = 12


def parse_patterns(raw: bytes, pat_pos: int, typ_pos: int, header: int):
    if len(raw) < header + PATTERN_SIZE:
        return None
    pat_count = raw[pat_pos]
    typ_count = raw[typ_pos]
    if not (1 <= pat_count <= 8 and 1 <= typ_count <= 8):
        return None
    if len(raw) < header + PATTERN_SIZE * pat_count:
        return None
    patterns = []
    for i in range(pat_count):
        base_offset = header + PATTERN_SIZE * i
        rate = raw[base_offset]
        count = raw[base_offset + 1]
        if not (1 <= count <= 4):
            return None
        for j in range(count):
            if raw[base_offset + PUT_OFFSET + PUT_SIZE * j] >= typ_count:
                return None
        patterns.append((rate, count))
    return patterns


def detect_scene_layout(raw_map: dict):
    best = None
    for pat_pos, typ_pos in ((1, 2), (0, 1), (2, 1), (1, 0)):
        for header in (4, 6, 8, 10, 12, 16):
            ok = sum(1 for raw in raw_map.values() if parse_patterns(raw, pat_pos, typ_pos, header) is not None)
            ratio = ok / max(1, len(raw_map))
            if best is None or ratio > best[0]:
                best = (ratio, pat_pos, typ_pos, header)
    return best


def average_units(raw: bytes, layout):
    if layout is None:
        return None
    patterns = parse_patterns(raw, layout[1], layout[2], layout[3])
    if not patterns:
        return None
    total_rate = sum(rate for rate, _ in patterns)
    if total_rate <= 0:
        return sum(count for _, count in patterns) / len(patterns)
    return sum(rate * count for rate, count in patterns) / total_rate


def extract_type_count(raw: bytes, layout) -> int:
    if layout is None or parse_patterns(raw, layout[1], layout[2], layout[3]) is None:
        return 1
    return max(1, int(raw[layout[2]]))


# ==================== DIAGNOSTIC D'UNE SCÈNE ====================
def read_scene_files(game_dir: Path, needed_ids):
    import UnityPy
    env = UnityPy.load(str(game_dir / "StreamingAssets" / "p0data2.bin"))
    found = {"folder_of": {}, "raw17": {}, "raw16": {}}
    raw16_ptrs = {}
    for path, ptr in env.container.items():
        norm = path.replace("\\", "/")
        m = SCENE_REGEX.search(norm)
        if m and int(m.group(2)) in needed_ids:
            found["folder_of"][int(m.group(2))] = m.group(1).lower()
            found["raw17"][int(m.group(2))] = raw_bytes(ptr)
            continue
        m = RAW16_REGEX.search(norm)
        if m:
            raw16_ptrs[m.group(1).lower()] = ptr
    for battle_id, folder in found["folder_of"].items():
        if folder in raw16_ptrs:
            found["raw16"][battle_id] = raw_bytes(raw16_ptrs[folder])
    return found


def hex_dump(raw: bytes, length: int) -> str:
    lines = []
    for i in range(0, min(length, len(raw)), 16):
        chunk = raw[i:i + 16]
        lines.append(f"      {i:04x}  {' '.join(f'{b:02x}' for b in chunk)}")
    return "\n".join(lines)


def inspect_scenes(arguments) -> None:
    stats, _, _ = base.load_database(base.DATABASE_PATH)
    wanted = {int(a) for a in arguments if a.isdigit()} or {67, 41, 127}
    print(f"Lecture de p0data2.bin pour les combats {sorted(wanted)}...")
    found = read_scene_files(base.GAME_DIR, wanted)
    for battle_id in sorted(wanted):
        info = stats.get(battle_id)
        label = (
            f"{info['name']} (niveau {info['lvl']}, PV {info['hp']}, force {info['strength']}, magie {info['magic']})"
            if info else "inconnu de la base"
        )
        print(f"== Combat {battle_id} : {label}")
        for key in ("raw16", "raw17"):
            raw = found[key].get(battle_id)
            if raw is None:
                print(f"   {key} : absent")
                continue
            print(f"   {key} : {len(raw)} octets, dossier {found['folder_of'].get(battle_id)}")
            print(hex_dump(raw, 128))
            if info:
                hp = info["hp"]
                offsets = [i for i in range(0, len(raw) - 1) if int.from_bytes(raw[i:i + 2], "little") == hp][:8]
                print(f"   positions où apparaît la valeur {hp} (2 octets) : {offsets}")


# ==================== CHOIX DES REMPLAÇANTS ====================
def usable_as_source(battle_id: int, data: dict) -> bool:
    folder = data["folder_of"].get(battle_id)
    if folder is None or battle_id not in data["raw17"] or folder not in data["raw16"]:
        return False
    if any((lang, folder) not in data["script"] for lang in LANGUAGES):
        return False
    return all((lang, battle_id) in data["text"] for lang in LANGUAGES)


def usable_as_target(battle_id: int, data: dict) -> bool:
    folder = data["folder_of"].get(battle_id)
    return folder is not None and len(data["folder_ids"].get(folder, ())) == 1


def choose_swaps(pool, stats, data, rng):
    sources = [b for b in pool if usable_as_source(b, data)]
    swaps = {}
    skipped = {}
    max_ratio = setting("SWAP_MAX_HP_RATIO")
    selection = setting("SWAP_SELECTION")
    for target in pool:
        if not usable_as_target(target, data):
            skipped[target] = "dossier de combat partagé avec un autre combat"
            continue
        candidates = [b for b in sources if b != target]
        if selection == "level" and target in stats:
            candidates = base.candidates_by_toughness(target, [b for b in candidates if b in stats], stats)
        elif selection == "wide" and target in stats:
            window = setting("SWAP_LEVEL_WINDOW")
            wide_ratio = setting("SWAP_WIDE_HP_RATIO")
            close = [
                b for b in candidates
                if abs(stats[b]["lvl"] - stats[target]["lvl"]) <= window
                and stats[b]["hp"] <= max(1, stats[target]["hp"]) * wide_ratio
            ]
            if len(close) < MIN_CANDIDATES:
                close = sorted(candidates, key=lambda b: abs(stats[b]["lvl"] - stats[target]["lvl"]))[:MIN_CANDIDATES]
            candidates = close
        elif max_ratio is not None and target in stats:
            limit = max(1, stats[target]["hp"]) * max_ratio
            capped = [b for b in candidates if stats[b]["hp"] <= limit]
            if len(capped) >= MIN_CANDIDATES:
                candidates = capped
            else:
                candidates = sorted(candidates, key=lambda b: stats[b]["hp"])[:MIN_CANDIDATES]
        if candidates:
            swaps[target] = rng.choice(candidates)
        else:
            skipped[target] = "aucun remplaçant disponible"
    return swaps, skipped, sources


# ==================== ÉCRITURE DU MOD ====================
def clean_previous_output(mod_dir: Path) -> None:
    for relative in (
        SCENE_DIR, SCRIPT_DIR,
        TEXT_DIR / "US", TEXT_DIR / "UK", TEXT_DIR / "JP",
        TEXT_DIR / "ES", TEXT_DIR / "FR", TEXT_DIR / "GR", TEXT_DIR / "IT",
    ):
        target = mod_dir / relative
        if target.exists():
            shutil.rmtree(target)
    field_scripts = mod_dir / "StreamingAssets" / "Assets" / "Resources" / "commonasset" / "eventengine" / "eventbinary" / "field"
    if field_scripts.exists():
        shutil.rmtree(field_scripts)
        print("   Anciens scripts de champs du randomizer supprimés (ils ne servent plus).")
    for useless in (
        mod_dir / "FF9_Data" / "EmbeddedAsset" / "Manifest" / "Sounds" / "BtlEncountBgmMetaData.txt",
        mod_dir / "StreamingAssets" / "Scripts" / "Sources" / "RandomizerEnemyScaling.cs",
        mod_dir / "StreamingAssets" / "Scripts" / "Sources" / "RandomizerLevelScaling.cs",
        mod_dir / "StreamingAssets" / "Scripts" / f"Memoria.Scripts.{mod_dir.name}.dll",
        mod_dir / "ModFileList.txt",
    ):
        if useless.exists():
            useless.unlink()
            print(f"   Supprimé : {useless.name}")


def patch_block(index: int, ref: dict, factor: float) -> list:
    lines = [f"= Enemy: {index} ="]
    fields = (
        ("Level", "lvl", False), ("MaxHP", "hp", True), ("Speed", "speed", False),
        ("Strength", "strength", False), ("Magic", "magic", False), ("Spirit", "spirit", False),
        ("PhysicalDefence", "defence", False), ("PhysicalEvade", "evade", False),
        ("MagicalDefence", "mdefence", False), ("MagicalEvade", "mevade", False),
        ("WinExp", "exp", True), ("WinGil", "gil", True),
    )
    for label, key, scaled in fields:
        if key not in ref:
            continue
        value = round(ref[key] * factor) if scaled else ref[key]
        lines.append(f"{label}: {max(1, value) if label == 'MaxHP' else value}")
    return lines


def unit_factor(target: int, source: int, units: dict) -> float:
    n_target = units.get(target)
    n_source = units.get(source)
    if not n_target or not n_source:
        return 1.0
    return max(0.2, min(5.0, n_target / n_source))


def write_battle_patch(mod_dir: Path, swaps: dict, stats: dict, units: dict, type_counts: dict) -> int:
    lines = []
    blocks = 0
    extra_types = int(setting("SWAP_EXTRA_TYPES", 0))
    for target in sorted(swaps):
        ref = stats.get(target)
        if ref is None:
            continue
        source = swaps[target]
        source_info = stats.get(source, {})
        # Couvre automatiquement tous les types d'ennemis présents dans le combat source
        num_types = max(
            source_info.get("type_count", 1),
            type_counts.get(source, 1),
            1 + extra_types,
        )
        factor = unit_factor(target, source, units)
        blocks += 1
        lines.append(f"== Battle: {target} ==")
        for index in range(num_types):
            lines.extend(patch_block(index, ref, factor))
        lines.append("")
    patch_file = mod_dir / "BattlePatch.txt"
    if setting("SWAP_SCALE_STATS") and lines:
        patch_file.write_text("\n".join(lines), encoding="utf-8")
        return blocks
    if patch_file.exists():
        patch_file.unlink()
    return 0


def write_swaps(mod_dir: Path, swaps: dict, data: dict) -> int:
    written = 0
    for target, source in swaps.items():
        target_folder = data["folder_of"][target].upper()
        source_folder = data["folder_of"][source]

        scene_out = mod_dir / SCENE_DIR / target_folder
        scene_out.mkdir(parents=True, exist_ok=True)
        (scene_out / f"{target}.raw17.bytes").write_bytes(data["raw17"][source])
        (scene_out / "dbfile0000.raw16.bytes").write_bytes(raw_bytes(data["raw16"][source_folder]))

        for lang in LANGUAGES:
            script_out = mod_dir / SCRIPT_DIR / lang.upper()
            script_out.mkdir(parents=True, exist_ok=True)
            (script_out / f"{scene_out.name}.eb.bytes").write_bytes(raw_bytes(data["script"][(lang, source_folder)]))

            text_out = mod_dir / TEXT_DIR / lang.upper() / "Battle"
            text_out.mkdir(parents=True, exist_ok=True)
            (text_out / f"{target}.mes").write_bytes(raw_bytes(data["text"][(lang, source)]))
        written += 1
    return written


def warn_about_exported_text(game_dir: Path) -> None:
    found = []
    for lang in LANGUAGES:
        folder = game_dir / "StreamingAssets" / "Text" / lang.upper() / "Battle"
        if folder.exists() and any(folder.iterdir()):
            found.append(folder)
    if found:
        print("[ATTENTION] Des textes de combat exportés existent et peuvent écraser ceux du randomizer :")
        for folder in found[:3]:
            print(f"   {folder}")
        print("   -> Supprime ces dossiers 'Battle', ou mets 'Text = 0' dans la section [Import] de Memoria.ini.")


def save_swap_log(seed, swaps, skipped, stats, units) -> None:
    entries = {}
    for target, source in swaps.items():
        entries[str(target)] = {
            "remplace_par": source,
            "nom_origine": stats.get(target, {}).get("name", "Inconnu"),
            "nom_nouveau": stats.get(source, {}).get("name", "Inconnu"),
            "niveau_origine": stats.get(target, {}).get("lvl", 0),
            "niveau_nouveau": stats.get(source, {}).get("lvl", 0),
            "facteur_taille_groupe": round(unit_factor(target, source, units), 2),
        }
    for target, reason in skipped.items():
        entries[str(target)] = {
            "intact": reason,
            "nom_origine": stats.get(target, {}).get("name", "Inconnu"),
        }
    SWAP_LOG_FILE.write_text(
        json.dumps({"graine": seed, "combats": entries}, indent=1, ensure_ascii=False),
        encoding="utf-8",
    )


def explain_field(field_id: int) -> None:
    if not SWAP_LOG_FILE.exists():
        print(f"Aucun '{SWAP_LOG_FILE}' : lance d'abord le script pour générer le mod.")
        return
    log = json.loads(SWAP_LOG_FILE.read_text(encoding="utf-8"))["combats"]
    found = False
    for fpath in base.SCRIPTS_INPUT_DIR.glob("*.txt"):
        text = fpath.read_text(encoding="utf-8", errors="replace")
        m_field = base.FIELDID_REGEX.search(text)
        if not m_field or int(m_field.group(1)) != field_id:
            continue
        found = True
        header = re.search(r"#HW fileid \d+ // (.*)", text)
        print(f"Champ {field_id} : {header.group(1).strip() if header else ''}")
        ids = []
        for m in base.BATTLE_REGEX.finditer(text):
            for i in range(2, 6):
                b_id = int(m.group(i))
                if b_id > 0 and b_id not in ids:
                    ids.append(b_id)
        for b_id in ids:
            entry = log.get(str(b_id))
            if entry is None:
                print(f"   combat {b_id} : pas dans la liste du randomizer (boss, combat spécial ou inconnu de la base) -> inchangé")
            elif "intact" in entry:
                print(f"   combat {b_id} ({entry['nom_origine']}) : INCHANGÉ, raison : {entry['intact']}")
            else:
                print(f"   combat {b_id} ({entry['nom_origine']}, niv {entry['niveau_origine']}) <- {entry['nom_nouveau']} (niv {entry['niveau_nouveau']}, contenu du combat {entry['remplace_par']})")
    if not found:
        print(f"Champ {field_id} introuvable dans les scripts texte.")


def run(check_only: bool = False) -> None:
    seed = base.SEED if base.SEED is not None else random.randrange(1, 10**9)

    stats, boss_ids, loaded = base.load_database(base.DATABASE_PATH)
    if not loaded:
        print(f"[ERREUR] Base de données introuvable : '{base.DATABASE_PATH}'")
        return
    ordered_ids, _, _ = base.load_text_info(base.SCRIPTS_INPUT_DIR)
    pool = [b for b in ordered_ids if b not in boss_ids and b in stats]
    print(f"1. {len(pool)} combats aléatoires hors boss.")

    print("2. Lecture des archives du jeu (cela peut prendre quelques minutes) :")
    data = read_archives(base.GAME_DIR, set(pool))
    sources = [b for b in pool if usable_as_source(b, data)]
    targets = [b for b in pool if usable_as_target(b, data)]
    print(f"   Scènes trouvées : {len(data['raw17'])} sur {len(pool)}")
    print(f"   Scripts de combat : {len(data['script'])} (attendu {len(LANGUAGES)} par dossier)")
    print(f"   Textes de combat : {len(data['text'])} (attendu {len(LANGUAGES)} par combat)")
    print(f"   Combats utilisables comme source : {len(sources)} ; comme cible : {len(targets)}")
    if not sources or not targets:
        print("[ERREUR] Il manque des éléments (voir les chiffres ci-dessus), rien n'est écrit.")
        return

    units = {}
    type_counts = {}
    candidates_layout = []
    raw16_by_id = {}
    for b in pool:
        folder = data["folder_of"].get(b)
        if folder in data["raw16"]:
            raw16_by_id[b] = raw_bytes(data["raw16"][folder])
    for label, mapping in (("raw16", raw16_by_id), ("raw17", data["raw17"])):
        found = detect_scene_layout(mapping)
        if found:
            candidates_layout.append((found[0], label, found, mapping))
    candidates_layout.sort(key=lambda item: -item[0])
    if candidates_layout and candidates_layout[0][0] >= 0.9:
        ratio, label, layout, mapping = candidates_layout[0]
        units = {b: average_units(raw, layout) for b, raw in mapping.items()}
        units = {b: n for b, n in units.items() if n}
        type_counts = {b: extract_type_count(raw, layout) for b, raw in mapping.items()}
        print(f"   Nombre d'ennemis par groupe : lecture validée sur {ratio * 100:.0f} % des scènes ({label}, décalage {layout[3]})")
        examples = [(b, units[b]) for b in pool if b in units and stats[b]["name"].lower().startswith("zombie")][:3]
        for b, n in examples:
            print(f"      ex. combat {b} ({stats[b]['name']}) : {n:.1f} ennemis en moyenne par groupe")
    else:
        found = ", ".join(f"{label} {ratio * 100:.0f} %" for ratio, label, _, _ in candidates_layout) or "0 %"
        print(f"   [ATTENTION] Nombre d'ennemis par groupe non lisible (concordance : {found}).")
        print("      Les PV ne sont pas répartis selon la taille du groupe. Lance : python battle_swap.py scene 67 41 127")

    rng = random.Random(seed)
    swaps, skipped, _ = choose_swaps(pool, stats, data, rng)
    print(f"3. {len(swaps)} combats remplacés, {len(skipped)} laissés intacts. Graine : {seed}")
    gaps = [abs(stats[source]["lvl"] - stats[target]["lvl"]) for target, source in swaps.items()]
    if gaps:
        far = sum(1 for g in gaps if g > 15)
        print(f"   Écart de niveau natif entre l'ennemi d'origine et son remplaçant : {sum(gaps) / len(gaps):.1f} en moyenne, {100 * far / len(gaps):.0f} % au-delà de 15 niveaux")
    for target, reason in list(skipped.items())[:10]:
        print(f"   intact : combat {target} ({stats[target]['name']}) - {reason}")
    for target in list(swaps)[:6]:
        source = swaps[target]
        print(f"   ex. combat {target} ({stats[target]['name']}, niv {stats[target]['lvl']}) <- {stats[source]['name']} (niv {stats[source]['lvl']}, PV {stats[source]['hp']})")

    if check_only:
        print("Mode 'check' : rien n'a été écrit.")
        return

    mod_dir = base.GAME_DIR / base.MOD_FOLDER_NAME
    clean_previous_output(mod_dir)
    written = write_swaps(mod_dir, swaps, data)
    patched = write_battle_patch(mod_dir, swaps, stats, units, type_counts)
    save_swap_log(seed, swaps, skipped, stats, units)
    print(f"4. {written} combats écrits dans '{mod_dir}'.")
    print(f"5. BattlePatch.txt : {patched} combats avec stats alignées sur l'ennemi remplacé.")
    print(f"6. Détail de chaque remplacement enregistré dans '{SWAP_LOG_FILE}' (voir : python battle_swap.py explain NUMERO_DE_CHAMP).")
    warn_about_exported_text(base.GAME_DIR)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "diagnose":
        diagnose_texts(base.GAME_DIR)
        return
    if len(sys.argv) > 1 and sys.argv[1] == "scene":
        inspect_scenes(sys.argv[2:])
        return
    if len(sys.argv) > 2 and sys.argv[1] == "explain" and sys.argv[2].isdigit():
        explain_field(int(sys.argv[2]))
        return
    run(check_only=len(sys.argv) > 1 and sys.argv[1] == "check")


if __name__ == "__main__":
    main()