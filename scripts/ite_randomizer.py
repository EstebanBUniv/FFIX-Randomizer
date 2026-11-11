import re
import csv
import random
import struct
import collections
from pathlib import Path

# ==================== CONFIGURATION ====================
GAME_DIR = Path(r"C:\Program Files (x86)\Steam\steamapps\common\FINAL FANTASY IX")
MOD_FOLDER_NAME = "RandomizerTest"

SCRIPTS_INPUT_DIR = Path("../fieldsScript")
EB_RELATIVE = Path("StreamingAssets/Assets/Resources/commonasset/eventengine/eventbinary/field")
ITEMS_RELATIVE = Path("StreamingAssets/Data/Items")

SOURCE = "bundle" # ou "folder" (comme pour les combats)
LANGUAGES = ("us", "uk", "jp", "es", "fr", "gr", "it")
SEED = None

# Plages d'IDs des objets (0 à 223 = Équipements / 224 à 254 = Consommables)
# On ignore les IDs 255 (Gils) et >= 256 (Objets Clés) pour ne pas casser le jeu.
SAFE_ITEMS_RANGE = range(0, 255)
# =======================================================

EVT_REGEX = re.compile(r'#HW fileid \d+ // (.*)')
ADD_ITEM_REGEX = re.compile(r'AddItem\(\s*(\d+)\s*,\s*(\d+)\s*\)')

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

# ==================== 1. RANDOMISATION DES COFFRES (Patch Binaire) ====================
def randomize_chests(rng: random.Random):
    print("--- 1. Randomisation des Coffres et Objets cachés (Scripts .eb.bytes) ---")

    expected_pairs = set()
    total_chests_found = 0

    for fpath in SCRIPTS_INPUT_DIR.glob("*.txt"):
        text = fpath.read_text(encoding="utf-8", errors="replace")
        for m in ADD_ITEM_REGEX.finditer(text):
            iid, qty = int(m.group(1)), int(m.group(2))
            if 0 <= iid < 255 and 0 < qty < 255:
                expected_pairs.add((iid, qty))
                total_chests_found += 1

    print(f"   -> {total_chests_found} objets normaux ({len(expected_pairs)} paires uniques) trouvés dans les textes.")
    if not expected_pairs:
        print("[ERREUR] Aucun AddItem trouvé dans SCRIPTS_INPUT_DIR.")
        return

    # On écarte les très petits IDs (0..4) uniquement pendant la détection pour éviter le bruit binaire
    detect_pairs = {(iid, qty) for iid, qty in expected_pairs if iid >= 5} or expected_pairs

    bundle_path = GAME_DIR / "StreamingAssets" / "p0data7.bin"
    print("   -> Chargement des binaires de champs depuis p0data7.bin...")
    raw_source = iter_from_bundle(bundle_path) if SOURCE == "bundle" else iter_from_folder(GAME_DIR / EB_RELATIVE)
    all_files = [(lang, fname, data) for lang, fname, data in raw_source if lang in LANGUAGES]

    if not all_files:
        print("[ERREUR] Aucun fichier .eb.bytes trouvé.")
        return

    sample_lang = "us" if any(l == "us" for l, _, _ in all_files) else all_files[0][0]
    sample_files = [data for lang, _, data in all_files if lang == sample_lang]

    # Dans FFIX, AddItem encode l'ID d'objet sur 2 octets (<HB ou <HH)
    formats_to_try = ["<HB", "<HH"]
    distinct_hits_2b = collections.defaultdict(set)
    total_hits_2b = collections.Counter()

    print("   -> Analyse des binaires pour déduire les signatures de 'AddItem' et 'SetTextVariable'...")
    for data in sample_files:
        for iid, qty in detect_pairs:
            for fmt in formats_to_try:
                needle = struct.pack(fmt, iid, qty)
                start = 0
                while True:
                    pos = data.find(needle, start)
                    if pos < 0:
                        break
                    if pos >= 2:
                        key2 = (data[pos - 2 : pos], fmt)
                        distinct_hits_2b[key2].add((iid, qty))
                        total_hits_2b[key2] += 1
                    start = pos + 1

    if not distinct_hits_2b:
        print("[ERREUR] Impossible de déduire l'opcode de AddItem. Les coffres ne seront pas modifiés.")
        return

    best_2b = max(
        distinct_hits_2b.keys(),
        key=lambda k: (len(distinct_hits_2b[k]), k[0][1] == 0, -abs(total_hits_2b[k] - total_chests_found))
    )
    PREFIX, FORMAT = best_2b
    hex_prefix = " ".join(f"0x{b:02X}" for b in PREFIX)
    print(f"   -> Signature AddItem détectée : [{hex_prefix}] (Format {FORMAT}) | "
          f"{len(distinct_hits_2b[best_2b])}/{len(detect_pairs)} paires ({total_hits_2b[best_2b]} occurrences).")

    # Auto-détection de SetTextVariable(slot, iid) au voisinage immédiat de chaque AddItem
    # Dans FFIX : [OPCODE (0x6B), FLAG (0x00), slot (1 octet), iid (2 octets <H)]
    needles = {
        PREFIX + struct.pack(FORMAT, iid, qty): (iid, qty)
        for iid, qty in expected_pairs
    }
    needle_len = len(PREFIX) + struct.calcsize(FORMAT)

    textvar_candidates = collections.Counter()
    for data in sample_files:
        for needle, (iid, _) in needles.items():
            if iid < 5:
                continue
            iid_bytes = struct.pack("<H", iid)
            start = 0
            while True:
                pos = data.find(needle, start)
                if pos < 0:
                    break
                win_start = max(0, pos - 120)
                win_end = min(len(data), pos + needle_len + 120)
                search_pos = win_start
                while True:
                    t_pos = data.find(iid_bytes, search_pos, win_end)
                    if t_pos < 0:
                        break
                    # Ignore la position de l'AddItem lui-même
                    if not (pos <= t_pos < pos + needle_len) and t_pos >= 3:
                        slot_byte = data[t_pos - 1]
                        if slot_byte < 16:
                            textvar_candidates[data[t_pos - 3 : t_pos - 1]] += 1
                    search_pos = t_pos + 1
                start = pos + 1

    TEXTVAR_PREFIX = textvar_candidates.most_common(1)[0][0] if textvar_candidates else b"\x6b\x00"
    tv_hex = " ".join(f"0x{b:02X}" for b in TEXTVAR_PREFIX)
    print(f"   -> Signature SetTextVariable détectée : [{tv_hex} <slot>] (Format <H).")

    mod_root = GAME_DIR / MOD_FOLDER_NAME / EB_RELATIVE
    written_files = 0
    patched_chests = 0
    patched_texts = 0
    base_seed = rng.randrange(1, 10**9)

    def patch_textvar_in_range(buf: bytearray, start_idx: int, end_idx: int, old_iid: int, new_iid: int, exclude_pos: int) -> int:
        """Remplace l'ID d'objet dans SetTextVariable(slot, old_iid) -> SetTextVariable(slot, new_iid)."""
        old_b = struct.pack("<H", old_iid)
        new_b = struct.pack("<H", new_iid)
        count_tv = 0
        s = start_idx
        while True:
            t_pos = buf.find(old_b, s, end_idx)
            if t_pos < 0:
                break
            if not (exclude_pos <= t_pos < exclude_pos + needle_len) and t_pos >= 3:
                if buf[t_pos - 3 : t_pos - 1] == TEXTVAR_PREFIX and buf[t_pos - 1] < 16:
                    buf[t_pos : t_pos + 2] = new_b
                    count_tv += 1
            s = t_pos + 1
        return count_tv

    for lang, fname, data in all_files:
        hit_positions = []
        for needle, (iid, qty) in needles.items():
            start = 0
            while True:
                pos = data.find(needle, start)
                if pos < 0:
                    break
                hit_positions.append((pos, iid, qty))
                start = pos + 1

        if not hit_positions:
            continue

        hit_positions.sort()
        patched = bytearray(data)
        last_end = -1
        modifications = 0

        for pos, iid, qty in hit_positions:
            if pos < last_end:
                continue
            # Graine liée au fichier et à l'ID d'origine pour synchroniser les 7 langues et les textes
            local_rng = random.Random(f"{base_seed}|{fname.lower()}|{iid}")
            new_id = local_rng.choice(SAFE_ITEMS_RANGE)

            # 1. Patch de AddItem(iid, qty) -> AddItem(new_id, qty)
            patched[pos : pos + needle_len] = PREFIX + struct.pack(FORMAT, new_id, qty)

            # 2. Patch de SetTextVariable(slot, iid) -> SetTextVariable(slot, new_id) autour du coffre
            tv_fixed = patch_textvar_in_range(
                patched,
                max(0, pos - 150),
                min(len(patched), pos + needle_len + 150),
                iid,
                new_id,
                pos,
            )
            # Si SetTextVariable est dans une autre fonction du même script de champ, on cherche dans tout le fichier
            if tv_fixed == 0:
                tv_fixed = patch_textvar_in_range(patched, 0, len(patched), iid, new_id, pos)

            last_end = pos + needle_len
            modifications += 1
            if lang == sample_lang:
                patched_chests += 1
                patched_texts += tv_fixed

        if modifications > 0:
            out_dir = mod_root / lang
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / fname).write_bytes(bytes(patched))
            written_files += 1

    stale_list = GAME_DIR / MOD_FOLDER_NAME / "ModFileList.txt"
    if stale_list.exists():
        stale_list.unlink()

    print(f"   Succès : {patched_chests} coffres et {patched_texts} textes (SetTextVariable) modifiés par langue ({written_files} fichiers écrits).\n")
    
# ==================== 2. RANDOMISATION DES MAGASINS ET FORGES (Fichiers CSV) ====================
EQUIPMENT_IDS = list(range(0, 224))    # Armes, armures, poignets, casques, accessoires
CONSUMABLE_IDS = list(range(224, 255)) # Potions, Éthers, Tentes, remèdes...

def load_csv(filepath: Path):
    if not filepath.exists():
        return None
    for enc in ("utf-8-sig", "cp1252", "iso-8859-1"):
        try:
            with filepath.open("r", encoding=enc) as f:
                return list(csv.reader(f, delimiter=";"))
        except UnicodeDecodeError:
            continue
    with filepath.open("r", encoding="utf-8", errors="replace") as f:
        return list(csv.reader(f, delimiter=";"))

def save_csv(filepath: Path, data: list):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    # Sauvegarde en UTF-8 sans BOM pour une compatibilité parfaite avec le parseur de Memoria
    with filepath.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerows(data)

def is_comment_or_empty(row: list) -> bool:
    return not row or not any(cell.strip() for cell in row) or row[0].lstrip().startswith("#")

def parse_int(val: str):
    # Extrait un entier même s'il y a des espaces autour
    s = val.strip()
    if s.startswith("-"):
        return int(s) if s[1:].isdigit() else None
    return int(s) if s.isdigit() else None

def randomize_shops(rng: random.Random):
    print("--- 2. Randomisation des Magasins (ShopItems.csv) ---")
    base_file = GAME_DIR / ITEMS_RELATIVE / "ShopItems.csv"
    shop_file = GAME_DIR / MOD_FOLDER_NAME / ITEMS_RELATIVE / "ShopItems.csv"

    # On repart toujours du fichier propre d'origine pour ne pas relire un fichier corrompu
    source_file = base_file if base_file.exists() else shop_file
    if not source_file.exists():
        print(f"[ATTENTION] ShopItems.csv introuvable ({base_file}). Magasins ignorés.")
        return

    data = load_csv(source_file)
    if not data:
        return

    shops_modified = 0
    examples = []

    # Structure Memoria : Col 0 = Comment | Col 1 = Id (NE PAS TOUCHER) | Col 2+ = Item0, Item1...
    for row in data:
        if is_comment_or_empty(row) or len(row) < 3:
            continue
        shop_id = parse_int(row[1])
        if shop_id is None:
            continue

        orig_items = []
        new_items = []
        used_in_shop = set()

        for i in range(2, len(row)):
            item_id = parse_int(row[i])
            # Ignore les emplacements vides (-1 ou vides) et les objets clés (>= 255)
            if item_id is None or item_id < 0 or item_id >= 255:
                continue

            orig_items.append(item_id)
            # Garde la cohérence : un slot d'équipement tire un équipement, un consommable tire un consommable
            pool = CONSUMABLE_IDS if item_id >= 224 else EQUIPMENT_IDS
            available = [x for x in pool if x not in used_in_shop] or pool
            picked = rng.choice(available)
            used_in_shop.add(picked)

            row[i] = str(picked)
            new_items.append(picked)

        if new_items:
            shops_modified += 1
            if len(examples) < 2:
                examples.append(f"   ex. Boutique {shop_id} ({row[0].strip()}) : {orig_items[:5]} -> {new_items[:5]}")

    save_csv(shop_file, data)
    for ex in examples:
        print(ex)
    print(f"   Succès : {shops_modified} boutiques randomisées dans '{shop_file}'.\n")

def randomize_synthesis(rng: random.Random):
    print("--- 3. Randomisation des Forges / Synthèse (Synthesis.csv) ---")
    base_file = GAME_DIR / ITEMS_RELATIVE / "Synthesis.csv"
    synth_file = GAME_DIR / MOD_FOLDER_NAME / ITEMS_RELATIVE / "Synthesis.csv"

    # On repart toujours du fichier propre d'origine
    source_file = base_file if base_file.exists() else synth_file
    if not source_file.exists():
        print(f"[ATTENTION] Synthesis.csv introuvable ({base_file}). Forges ignorées.")
        return

    data = load_csv(source_file)
    if not data:
        return

    recipes_modified = 0
    examples = []

    # Structure Memoria :
    # Col 0 = Comment | Col 1 = Id | Col 2 = Shops | Col 3 = Price | Col 4 = Result | Col 5+ = Ingredients
    for row in data:
        if is_comment_or_empty(row) or len(row) < 6:
            continue
        recipe_id = parse_int(row[1])
        orig_result = parse_int(row[4])
        if recipe_id is None or orig_result is None:
            continue

        # 1. Nouvel objet forgé (Colonne 4 : Result) -> on tire un équipement (0..223)
        new_result = rng.choice(EQUIPMENT_IDS)
        row[4] = str(new_result)

        # 2. Nouveaux ingrédients (Colonne 5+ : soit séparés par des virgules dans row[5], soit sur row[5], row[6]...)
        new_ing_list = []
        if "," in row[5]:
            parts = row[5].split(",")
            new_parts = []
            for p in parts:
                if parse_int(p) is not None:
                    ing = rng.choice(SAFE_ITEMS_RANGE)
                    new_parts.append(str(ing))
                    new_ing_list.append(ing)
                else:
                    new_parts.append(p)
            row[5] = ", ".join(new_parts)
        else:
            for c in range(5, len(row)):
                val = parse_int(row[c])
                if val is not None and 0 <= val < 255:
                    ing = rng.choice(SAFE_ITEMS_RANGE)
                    row[c] = str(ing)
                    new_ing_list.append(ing)

        recipes_modified += 1
        if len(examples) < 2:
            examples.append(f"   ex. Recette {recipe_id} ({row[0].strip()}) : Résultat {orig_result} -> {new_result} | Ingrédients -> {new_ing_list}")

    save_csv(synth_file, data)
    for ex in examples:
        print(ex)
    print(f"   Succès : {recipes_modified} recettes de forge randomisées dans '{synth_file}'.\n")

if __name__ == "__main__":
    rng = random.Random(SEED if SEED is not None else random.randrange(1, 10**9))
    randomize_chests(rng)
    randomize_shops(rng)
    randomize_synthesis(rng)

    # Suppression de ModFileList.txt à la toute fin pour forcer Memoria à recharger les CSV et les .eb
    stale_list = GAME_DIR / MOD_FOLDER_NAME / "ModFileList.txt"
    if stale_list.exists():
        stale_list.unlink()
        
# Erreur : Zone de début non aléatoire, quelque zone de l'atlas non aléatoire, chocobo peut être non aléatoire, ennemi scripté non aléatoire