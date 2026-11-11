import re
import sys
import json
import shutil
import struct
import random
from pathlib import Path

# ==================== CONFIGURATION ====================
GAME_DIR = Path(r"C:\Program Files (x86)\Steam\steamapps\common\FINAL FANTASY IX")
MOD_FOLDER_NAME = "RandomizerTest"

SCRIPTS_INPUT_DIR = Path("../fieldsScript")

# Modes disponibles : "swap" (recommandé, via battle_swap.py), "level", "window" ou "full"
MODE = "swap"
WINDOW_RADIUS = 15
LEVEL_TOLERANCE = 6
MAX_DEFENCE_GAP = 2
MAX_MAGIC_DEFENCE_GAP = 3
MAX_HP_RATIO = 2.5
MIN_POOL = 8

# Réglages utilisés par battle_swap.py (MODE == "swap")
SWAP_SELECTION = "wide"
SWAP_LEVEL_WINDOW = 12
SWAP_WIDE_HP_RATIO = 15.0
SWAP_MAX_HP_RATIO = 40.0
SWAP_SCALE_STATS = True
SWAP_EXTRA_TYPES = 0

DATABASE_PATH = Path("FF9_Database_Propre.json")
FALLBACK_BOSS_IDS = {138, 150, 166, 168}
SEED = None

SOURCE = "bundle"

MUSIC_FIX = True
MUSIC_METADATA_FILE = Path("BtlEncountBgmMetaData.txt")

LANGUAGES = None
EB_RELATIVE = Path("StreamingAssets/Assets/Resources/commonasset/eventengine/eventbinary/field")
# =======================================================

BATTLE_REGEX = re.compile(
    r"SetRandomBattles\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)"
)
NUMBER_REGEX = re.compile(r"(\d+)")
FIELDID_REGEX = re.compile(r"#HW fileid (\d+)")


# ==================== LECTURE DES SCRIPTS TEXTE ====================
# Les scripts texte servent à connaître les groupes d'ennemis valides
# (dans l'ordre de la progression) et les combinaisons d'IDs à retrouver
# dans les fichiers .eb binaires.
def load_text_info(directory: Path):
    files = sorted(
        directory.glob("*.txt"),
        key=lambda p: int(NUMBER_REGEX.search(p.stem).group(1)) if NUMBER_REGEX.search(p.stem) else 999999,
    )
    ordered_ids = []
    seen = set()
    tuples = {}
    statements = 0
    for fpath in files:
        text = fpath.read_text(encoding="utf-8", errors="replace")
        for m in BATTLE_REGEX.finditer(text):
            statements += 1
            pat = int(m.group(1))
            ids = tuple(int(m.group(i)) for i in range(2, 6))
            for b_id in ids:
                if b_id > 0 and b_id not in seen:
                    seen.add(b_id)
                    ordered_ids.append(b_id)
            if any(ids) and pat < 256 and max(ids) < 65536:
                tuples.setdefault(struct.pack("<4H", *ids), set()).add(pat)
    return ordered_ids, tuples, statements


# ==================== RECHERCHE DANS UN .eb ====================
def find_matches(data: bytes, tuples: dict):
    found = []
    suspects = 0
    for needle, pats in tuples.items():
        start = 0
        while True:
            pos = data.find(needle, start)
            if pos < 0:
                break
            start = pos + 1
            if pos >= 1 and data[pos - 1] in pats:
                found.append(pos)
            else:
                suspects += 1
    found.sort()
    clean = []
    last_end = -1
    for pos in found:
        if pos - 1 >= last_end:
            clean.append(pos)
            last_end = pos + 8
    return clean, suspects


# ==================== BASE DE DONNÉES DES ENNEMIS ====================
# Le JSON donne, pour chaque combat, le niveau et les statistiques de ses ennemis.
# Les PV, l'EXP et les Gils sont moyennés par type d'ennemi présent dans le JSON
# afin d'éviter de les multiplier deux fois lors de l'ajustement par taille de groupe.
def load_database(path: Path):
    stats = {}
    boss_ids = set(FALLBACK_BOSS_IDS)
    if not path.exists():
        return stats, boss_ids, False

    def num(enemy, key):
        try:
            return int(enemy[key])
        except (KeyError, ValueError, TypeError):
            return 0

    data = json.loads(path.read_text(encoding="utf-8"))
    for key, battle in data.get("ennemis_lambda", {}).items():
        enemies = [e for e in battle.get("Ennemis", []) if "battle.enemy.lvl" in e]
        if enemies:
            count = len(enemies)
            stats[int(key)] = {
                "name": str(battle.get("Nom_Principal", "")),
                "type_count": count,
                "lvl": max(num(e, "battle.enemy.lvl") for e in enemies),
                "hp": max(1, round(sum(num(e, "battle.enemy.hp") for e in enemies) / count)),
                "defence": max(num(e, "battle.enemy.defence") for e in enemies),
                "mdefence": max(num(e, "battle.enemy.magic_defence") for e in enemies),
                "strength": max(num(e, "battle.enemy.strength") for e in enemies),
                "magic": max(num(e, "battle.enemy.magic") for e in enemies),
                "exp": round(sum(num(e, "battle.enemy.exp") for e in enemies) / count),
                "gil": round(sum(num(e, "battle.enemy.gils") for e in enemies) / count),
                "speed": max(num(e, "battle.enemy.speed") for e in enemies),
                "spirit": max(num(e, "battle.enemy.spirit") for e in enemies),
                "evade": max(num(e, "battle.enemy.evade") for e in enemies),
                "mevade": max(num(e, "battle.enemy.magic_evade") for e in enemies),
            }
    for key in data.get("boss", {}):
        boss_ids.add(int(key))
    for key in data.get("monstres_amicaux", {}):
        boss_ids.add(int(key))
    return stats, boss_ids, True


# ==================== CHOIX D'UN REMPLAÇANT PAR NIVEAU ET RÉSISTANCE ====================
def candidates_by_toughness(orig_id: int, pool, stats: dict):
    ref = stats[orig_id]
    best = []
    for step in range(0, 14):
        tol = LEVEL_TOLERANCE + 2 * step
        d_gap = MAX_DEFENCE_GAP + 2 * step
        m_gap = MAX_MAGIC_DEFENCE_GAP + 2 * step
        hp_ratio = MAX_HP_RATIO * (1.3 ** step)
        best = [
            b for b in pool
            if b != orig_id
            and abs(stats[b]["lvl"] - ref["lvl"]) <= tol
            and stats[b]["defence"] <= ref["defence"] + d_gap
            and stats[b]["mdefence"] <= ref["mdefence"] + m_gap
            and stats[b]["hp"] <= max(1, ref["hp"]) * hp_ratio
        ]
        if len(best) >= MIN_POOL:
            return best
    return sorted((b for b in pool if b != orig_id), key=lambda b: abs(stats[b]["lvl"] - ref["lvl"]))[:MIN_POOL]


# ==================== SOURCE DES .eb D'ORIGINE ====================
def iter_from_bundle(bundle_path: Path):
    import UnityPy
    env = UnityPy.load(str(bundle_path))
    for path, ptr in env.container.items():
        norm = path.replace("\\", "/")
        low = norm.lower()
        if "/eventbinary/field/" not in low or not low.endswith(".eb.bytes"):
            continue
        parts = norm.split("/")
        lang = parts[-2].lower()
        name = parts[-1]
        asset = ptr.read()
        raw = asset.m_Script
        data = raw.encode("utf-8", "surrogateescape") if isinstance(raw, str) else bytes(raw)
        yield lang, name, data


def iter_from_folder(src_root: Path):
    for lang_dir in sorted(src_root.iterdir()):
        if lang_dir.is_dir():
            for fpath in sorted(lang_dir.glob("*.eb.bytes")):
                yield lang_dir.name.lower(), fpath.name, fpath.read_bytes()


# ==================== MUSIQUE DES COMBATS ====================
def read_music_metadata(game_dir: Path):
    if MUSIC_METADATA_FILE.exists():
        return json.loads(MUSIC_METADATA_FILE.read_text(encoding="utf-8")), f"fichier '{MUSIC_METADATA_FILE}'"
    import UnityPy
    for sub in ("x64", "x86"):
        path = game_dir / sub / "FF9_Data" / "resources.assets"
        if not path.exists():
            continue
        env = UnityPy.load(str(path))
        for obj in env.objects:
            if obj.type.name != "TextAsset":
                continue
            asset = obj.read()
            name = str(asset.m_Name).lower()
            if name.startswith("btlencountbgmmetadata"):
                return json.loads(asset.m_Script), f"'{path}'"
    return None, None


def json_key(value) -> str:
    return repr(value)


def merge_music_metadata(metadata: dict, pool_ids):
    updated = 0
    for room, battles in metadata.items():
        if not isinstance(battles, dict) or not battles:
            continue
        pool_values = [v for k, v in battles.items() if str(k).isdigit() and int(k) in pool_ids]
        if not pool_values:
            continue
        counts = {}
        for v in pool_values:
            counts[json_key(v)] = counts.get(json_key(v), 0) + 1
        best_key = max(counts, key=counts.get)
        default = next(v for v in pool_values if json_key(v) == best_key)
        for battle_id in pool_ids:
            key = str(battle_id)
            if key not in battles:
                battles[key] = default
        updated += 1
    return updated


def write_music_metadata(game_dir: Path, mod_dir: Path, pool_ids) -> None:
    target = mod_dir / "FF9_Data" / "EmbeddedAsset" / "Manifest" / "Sounds" / "BtlEncountBgmMetaData.txt"
    if not MUSIC_FIX:
        if target.exists():
            target.unlink()
        return
    try:
        metadata, origin = read_music_metadata(game_dir)
    except Exception as exc:
        print(f"5. [ATTENTION] Musique : lecture impossible ({exc}).")
        return
    if metadata is None:
        print("5. [ATTENTION] Musique : BtlEncountBgmMetaData.txt introuvable dans resources.assets.")
        print("   -> Exporte-le avec Hades Workshop (Tools > Unity Assets Viewer > resources.assets)")
        print(f"      puis place-le à côté du script sous le nom '{MUSIC_METADATA_FILE}'.")
        return
    pool_set = set(pool_ids)
    updated = merge_music_metadata(metadata, pool_set)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(metadata, indent=1), encoding="utf-8")
    print(f"5. Musique : {updated} champs mis à jour depuis {origin}.")
    print(f"   -> '{target}'")


# ==================== NETTOYAGE DES FICHIERS OBSOLÈTES ====================
def remove_old_scaling_scripts(mod_dir: Path) -> None:
    scripts_dir = mod_dir / "StreamingAssets" / "Scripts"
    for obsolete in (
        scripts_dir / "Sources" / "RandomizerEnemyScaling.cs",
        scripts_dir / "Sources" / "RandomizerLevelScaling.cs",
        scripts_dir / f"Memoria.Scripts.{mod_dir.name}.dll",
    ):
        if obsolete.exists():
            obsolete.unlink()
            print(f"   Ancien fichier script supprimé : '{obsolete.name}'")


def remove_swap_files(mod_dir: Path) -> None:
    removed = []
    for relative in (
        Path("StreamingAssets/Assets/Resources/BattleMap"),
        Path("StreamingAssets/Assets/Resources/CommonAsset/EventEngine/EventBinary/Battle"),
        Path("FF9_Data/EmbeddedAsset/Text"),
    ):
        target = mod_dir / relative
        if target.exists():
            shutil.rmtree(target)
            removed.append(relative.name)
    patch = mod_dir / "BattlePatch.txt"
    if patch.exists():
        patch.unlink()
        removed.append("BattlePatch.txt")
    if removed:
        print(f"6. Fichiers de battle_swap.py supprimés du mod : {', '.join(removed)}")


def main():
    if MODE == "swap":
        sys.modules.setdefault("eb_randomizer", sys.modules[__name__])
        import battle_swap
        battle_swap.run(check_only=len(sys.argv) > 1 and sys.argv[1] == "check")
        return

    check_only = len(sys.argv) > 1 and sys.argv[1] == "check"
    seed = SEED if SEED is not None else random.randrange(1, 10**9)

    if MODE not in ("level", "window", "full", "swap"):
        print(f"[ERREUR] MODE inconnu : '{MODE}' (choisir parmi : swap, level, window, full).")
        return
    if not SCRIPTS_INPUT_DIR.exists():
        print(f"[ERREUR] Le dossier '{SCRIPTS_INPUT_DIR}' n'existe pas.")
        return

    src_root = GAME_DIR / EB_RELATIVE
    bundle_path = GAME_DIR / "StreamingAssets" / "p0data7.bin"
    if SOURCE == "bundle" and not bundle_path.exists():
        print(f"[ERREUR] Fichier introuvable : '{bundle_path}'")
        return
    if SOURCE == "folder" and not src_root.exists():
        print(f"[ERREUR] Dossier des .eb d'origine introuvable : '{src_root}'")
        return

    ordered_ids, tuples, statements = load_text_info(SCRIPTS_INPUT_DIR)
    id_to_index = {b_id: idx for idx, b_id in enumerate(ordered_ids)}
    print(f"1. {len(ordered_ids)} groupes d'ennemis, {statements} SetRandomBattles dans les scripts texte.")

    stats, boss_ids, db_loaded = load_database(DATABASE_PATH)
    if MODE == "level" and not db_loaded:
        print(f"[ERREUR] Mode 'level' : base de données introuvable ('{DATABASE_PATH}').")
        return
    print(f"   Base de données : {'chargée' if db_loaded else 'absente'}, {len(stats)} combats avec statistiques, {len(boss_ids)} boss/amicaux exclus.")

    safe_ids = [b for b in ordered_ids if b not in boss_ids]
    pool = [b for b in safe_ids if b in stats] if stats else safe_ids

    def pick_replacement(orig_id: int, rng: random.Random) -> int:
        if orig_id == 0 or orig_id in boss_ids:
            return orig_id
        if MODE == "full":
            return rng.choice(pool)
        if MODE == "level":
            if orig_id not in stats:
                return orig_id
            return rng.choice(candidates_by_toughness(orig_id, pool, stats))
        if orig_id not in id_to_index:
            return rng.choice(pool)
        curr_idx = id_to_index[orig_id]
        start = max(0, curr_idx - WINDOW_RADIUS)
        end = min(len(ordered_ids) - 1, curr_idx + WINDOW_RADIUS)
        window = [b for b in ordered_ids[start : end + 1] if b not in boss_ids]
        return rng.choice(window) if window else orig_id

    wanted = {l.lower() for l in LANGUAGES} if LANGUAGES is not None else None
    if SOURCE == "bundle":
        print(f"2. Lecture de '{bundle_path}' (cela peut prendre une à deux minutes)...")
        source = iter_from_bundle(bundle_path)
    else:
        print(f"2. Lecture des .eb exportés dans '{src_root}'...")
        source = iter_from_folder(src_root)

    mod_root = GAME_DIR / MOD_FOLDER_NAME / EB_RELATIVE
    plans = []
    lang_stats = {}
    for lang, name, data in source:
        if wanted is not None and lang not in wanted:
            continue
        st = lang_stats.setdefault(lang, {"files": 0, "hit": 0, "matches": 0, "suspects": 0})
        st["files"] += 1
        positions, suspects = find_matches(data, tuples)
        st["suspects"] += suspects
        if positions:
            st["hit"] += 1
            st["matches"] += len(positions)
            plans.append((lang, name, data, positions))

    if not lang_stats:
        print("[ERREUR] Aucun fichier .eb de champ trouvé dans la source.")
        return
    for lang in sorted(lang_stats):
        st = lang_stats[lang]
        print(f"   {lang}: {st['files']} fichiers, {st['hit']} avec combats, "
              f"{st['matches']} SetRandomBattles trouvés, {st['suspects']} correspondances douteuses ignorées")
    print(f"   Attendu dans les scripts texte : environ {statements} (un peu plus si des branches [jp] existent).")

    if check_only:
        print("Mode 'check' : rien n'a été écrit.")
        return

    if not plans:
        print("[ERREUR] Aucun SetRandomBattles retrouvé, rien à écrire.")
        return

    mod_dir = GAME_DIR / MOD_FOLDER_NAME
    removed = 0
    if mod_dir.exists():
        for old in mod_dir.rglob("*.eb.bytes"):
            old.unlink()
            removed += 1
        old_bin = mod_dir / "StreamingAssets" / "p0data7.bin"
        if old_bin.exists():
            print(f"[ATTENTION] '{old_bin}' existe encore, déplace-le hors du dossier du mod.")
    print(f"3. {removed} anciens .eb supprimés du dossier du mod. Graine : {seed}")

    written = 0
    examples = []
    first_lang = sorted(lang_stats)[0]
    for lang_name, fname, data, positions in plans:
        patched = bytearray(data)
        stem = fname
        for k, pos in enumerate(positions):
            rng = random.Random(f"{seed}|{stem}|{k}")
            old_ids = struct.unpack_from("<4H", patched, pos)
            new_ids = [pick_replacement(oid, rng) for oid in old_ids]
            struct.pack_into("<4H", patched, pos, *new_ids)
            if len(examples) < 6 and lang_name == first_lang:
                examples.append((stem, old_ids, tuple(new_ids)))
        out_dir = mod_root / lang_name
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / fname).write_bytes(bytes(patched))
        written += 1

    print(f"4. {written} fichiers écrits dans '{mod_root}'.")
    for stem, old_ids, new_ids in examples:
        old_lv = [(stats[i]["lvl"], stats[i]["defence"]) if i in stats else "?" for i in old_ids]
        new_lv = [(stats[i]["lvl"], stats[i]["defence"]) if i in stats else "?" for i in new_ids]
        print(f"   ex. {stem} : {old_ids} -> {new_ids}  ((niveau, défense) {old_lv} -> {new_lv})")

    remove_old_scaling_scripts(mod_dir)
    write_music_metadata(GAME_DIR, mod_dir, safe_ids)
    remove_swap_files(mod_dir)

    stale_list = mod_dir / "ModFileList.txt"
    if stale_list.exists():
        stale_list.unlink()
        print("7. Ancien ModFileList.txt supprimé : Memoria le régénérera au prochain lancement du jeu.")


if __name__ == "__main__":
    main()