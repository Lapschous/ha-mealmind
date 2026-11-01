import json
import sqlite3
import time
import trafilatura
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import ollama
from urllib.parse import urlsplit

DB_PATH = "backend/src/db/recipes.db"

KEEP_KEYS = {
    "name", "description", "recipeYield", "prepTime", "cookTime", "totalTime",
    "recipeIngredient", "recipeInstructions", "recipeCuisine",
    "recipeCategory", "keywords", "suitableForDiet",
}

PROMPT = """
        You are a Data Normalization AI for a recipe pipeline. Extract unstructured recipe text (HTML or raw text) into a single, valid JSON object matching the structure below.
        ### TARGET JSON STRUCTURE
        {
        "recipe_meta": {
            "title": "String",
            "description": "String or null",
            "servings": "Integer (default to 0 if unspecified)",
            "preptime_minutes": "Integer (default to 0 if unspecified)",
            "cooktime_minutes": "Integer (default to 0 if unspecified)",
            "continent": "Asia | Europe | North America | South America | Africa | Oceania | null",
            "source": "String or null"
        },
        "recipe_ingredients": [
            {
            "name": "String (lowercase, base generic ingredient)",
            "amount": "Float or null",
            "unit": "g | kg | ml | l | tsp | tbsp | whole | clove | pinch | null",
            "step_number": "Integer or null (the step_number where this ingredient is first added)",
            "prep_method": "String or null (e.g., 'chopped', 'sliced', 'diced', 'minced')"
            }
        ],
        "recipe_steps": [
            {
            "step_number": 1,
            "instruction": "String",
            "next_step_number": "Integer or null (the step_number this step feeds into; null for the final step(s))",
            "duration_text": "String or null (e.g., '20 minutes', '5-10 minutes', '~30 minutes')"
            }
        ],
        "tags": [
            {
            "name": "String (lowercase, concise tag name)",
            "category": "Dietary | Cuisine | Meal Type | Equipment | null"
            }
        ]
        }

        ### NORMALIZATION RULES
1. UNITS & CONVERSIONS:
- Weights -> 'g' or 'kg'. Liquid volumes -> 'ml' or 'l'.
- Temperatures in step instructions -> Convert °F to °C (e.g., 350°F -> 180°C).
- Fractions -> Decimals (e.g., "1 1/2" -> 1.5).
- Whole items (e.g., "1 onion") -> amount: 1.0, unit: "whole".
- Unmeasured items (e.g., "salt to taste") -> amount: null, unit: null.

2. INGREDIENT CLEANING & EXTRACTION:
- You MUST extract EVERY single ingredient mentioned in the recipe list OR step instructions. Do not omit water, flour, salt, or other basic ingredients.
- Split the method e.g words like "chopped", "sliced", "diced", "minced" from the ingredient name
- "1 large brown onion, finely diced" -> name: "yellow onion", method: "finely diced"
- "2 tbsp extra virgin olive oil" -> name: "olive oil", method: None

3. TAG STANDARDIZATION & CATEGORIES:
- "Dietary": ONLY established diets (e.g., "gluten-free", "vegan", "vegetarian", "dairy-free", "low-carb").
- "Cuisine": Regional/cultural styles (e.g., "italian", "japanese", "german", "mexican").
- "Meal Type": Course or category (e.g., "breakfast", "dinner", "snack", "bread", "dessert", "side dish").
- "Equipment": Major kitchen tools or appliances (e.g., "oven", "air fryer", "blender", "stand mixer", "dutch oven").
- TAG RESTRICTIONS:
- "name" MUST be a concrete item/style (e.g., "vegan", "bread", "oven"). NEVER use the category names themselves (e.g., NEVER name: "dietary", "cuisine", "meal type").
- DO NOT tag instructions, actions, or environments (e.g., NEVER "warm place", "yeast based", "kneading").
- DO NOT tag textures, generic descriptors, or macros (e.g., NEVER "dense", "carbs", "fluffy", "tasty").
- Keep tag names lowercase, concise, and generic (e.g., "bread", not "rye bread").

4. OUTPUT & CONSTRAINTS:
- Use JSON null (without quotes), NEVER the text string "null".
- The "unit" key MUST ONLY use values from the allowed unit list. If a unit is non-standard (e.g., "thumb-sized piece"), convert it to 'whole' or set "unit": null.
- Ensure ingredient names remove prep states like "cooked", "canned", "sliced", or "frozen" (e.g., "cooked salmon fillet" -> "salmon fillet").

5. STEP GRAPH:
- Number steps 1..N in the order they are performed. Use these numbers in "step_number", "next_step_number", and ingredient "step_number".
- "next_step_number" is the step this step feeds into. Use null for the final step.
- For each ingredient, set "step_number" to the step where it is added. Use null if it is not tied to a step.
- Split each instruction into one atomic action per step before assigning step numbers    
- next_step_number: it must be numerically greater than step_number, never equal or less, and must refer to a step number that exists in the output (or be null).    
    """


def extract_json_ld(soup: BeautifulSoup) -> str | None:
    """Extracts JSON-LD recipe schema"""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            items = data if isinstance(data, list) else data.get("@graph", [data])
            for item in items:
                if item.get("@type") == "Recipe" or "Recipe" in item.get("@type", []):
                    trimmed = {k: v for k, v in item.items() if k in KEEP_KEYS}
                    return json.dumps(trimmed)
        except (json.JSONDecodeError, TypeError, AttributeError):
            continue
    return None

def _to_int(value) -> int | None:
    """Coerce an LLM-provided number to int, returning None if it isn't one."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

def receive_and_clean(url: str) -> str:
    """Fetches web content using Playwright and cleans HTML via JSON-LD or Trafilatura and BS4."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url)
        page.wait_for_load_state("domcontentloaded")

        html_content = page.content()
        browser.close()

    soup = BeautifulSoup(html_content, "html.parser")

    # Checks for json-ld structured data first
    json_ld = extract_json_ld(soup)
    if json_ld:
        return json_ld

    # If no json-ld, cleans html with trafilatura and BS4
    for tag in soup(["script", "style", "svg", "iframe", "button", "form", "noscript", "footer", "nav"]):
        tag.decompose()

    pruned_content = str(soup)

    clean_content = trafilatura.extract(
        pruned_content,
        include_links=False,
        favor_precision=False,
        include_images=False,
        include_comments=False,
        include_tables=False,
        include_formatting=True,
        output_format="markdown"
    )

    return clean_content


def scrape_with_llm(clean_content: str) -> dict:
    """Uses local llm to turn the md string into structured json"""
    response = ollama.chat(
        model="hf.co/mistralai/Ministral-3-8B-Instruct-2512-GGUF:Q4_K_M",
        format="json", 
        messages=[{"role": "user", "content": PROMPT + clean_content}],
        options = {"num_predict": 4096, "temperature": 0.3, "num_ctx":8192},
        keep_alive = 0
    )

    #Converts response to a python readable dict
    json_string = response.message.content
    recipe_data = json.loads(json_string)

    return recipe_data

def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    return f"{parts.scheme}://{parts.netloc.lower()}{parts.path.rstrip('/')}"

def store_recipe_in_db(normalized_url: str, recipe_data: dict, db_path=DB_PATH) -> None:
    """Stores the normalized recipe data, including the step graph, in a SQLite database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("PRAGMA foreign_keys = ON;")

    # 1. Create tables
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS recipe_meta (
            recipe_id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            servings INTEGER NOT NULL DEFAULT 0,
            preptime_minutes INTEGER NOT NULL DEFAULT 0,
            cooktime_minutes INTEGER NOT NULL DEFAULT 0,
            continent TEXT,
            source TEXT,
            source_url TEXT NOT NULL UNIQUE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ingredients (
            ingredient_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        );
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS recipe_steps (
            step_id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipe_id INTEGER NOT NULL REFERENCES recipe_meta(recipe_id) ON DELETE CASCADE,
            step_number INTEGER NOT NULL,
            instruction TEXT NOT NULL,
            next_step_id INTEGER REFERENCES recipe_steps(step_id) ON DELETE SET NULL,
            duration_text TEXT,
            UNIQUE (recipe_id, step_number)
        );
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS recipe_ingredients (
            recipe_ingredient_id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipe_id INTEGER NOT NULL REFERENCES recipe_meta(recipe_id) ON DELETE CASCADE,
            ingredient_id INTEGER NOT NULL REFERENCES ingredients(ingredient_id) ON DELETE CASCADE,
            amount REAL,
            unit TEXT,
            prep_method TEXT,
            step_id INTEGER REFERENCES recipe_steps(step_id) ON DELETE SET NULL
        );
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tags (
            tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            category TEXT
        );
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS recipe_tags (
            recipe_id INTEGER NOT NULL REFERENCES recipe_meta(recipe_id) ON DELETE CASCADE,
            tag_id INTEGER NOT NULL REFERENCES tags(tag_id) ON DELETE CASCADE,
            PRIMARY KEY (recipe_id, tag_id)
        );
    ''')

    # 2. Insert recipe metadata

    meta = recipe_data.get("recipe_meta", {})
    cursor.execute('''
        INSERT INTO recipe_meta (title, description, servings, preptime_minutes, cooktime_minutes, continent, source, source_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_url) DO NOTHING
    ''', (
        meta.get("title"),
        meta.get("description"),
        meta.get("servings", 0),
        meta.get("preptime_minutes", 0),
        meta.get("cooktime_minutes", 0),
        meta.get("continent"),
        meta.get("source"),
        normalized_url
    ))

    if cursor.rowcount == 1:
        recipe_id = cursor.lastrowid
    
        # 3. Insert steps first, without edges, so every step_id exists
        steps = [s for s in recipe_data.get("recipe_steps", []) if _to_int(s.get("step_number")) is not None]
        step_id_by_number: dict[int, int] = {}
        for step in steps:
            num = _to_int(step.get("step_number"))
            cursor.execute('''
                INSERT INTO recipe_steps (recipe_id, step_number, instruction, duration_text)
                VALUES (?, ?, ?, ?)
            ''', (recipe_id, num, step.get("instruction"), step.get("duration_text")))
            step_id_by_number[num] = cursor.lastrowid

        # 4. Wire the step graph
        for step in steps:
            num = _to_int(step.get("step_number"))
            nxt = _to_int(step.get("next_step_number"))
            if nxt is None or nxt not in step_id_by_number:
                continue
            cursor.execute('''
                UPDATE recipe_steps SET next_step_id = ?
                WHERE step_id = ?
            ''', (step_id_by_number[nxt], step_id_by_number[num]))

        # 5. Insert ingredients, linking each to the step where it's added
        for ing in recipe_data.get("recipe_ingredients", []):
            raw_name = ing.get("name")
            if not raw_name or not raw_name.strip():
                continue

            ing_name = raw_name.strip().lower()

            cursor.execute('''
                INSERT INTO ingredients (name) VALUES (?)
                ON CONFLICT(name) DO NOTHING
            ''', (ing_name,))

            cursor.execute('SELECT ingredient_id FROM ingredients WHERE name = ?', (ing_name,))
            row = cursor.fetchone()
            if not row:
                continue
            ingredient_id = row[0]

            step_id = step_id_by_number.get(_to_int(ing.get("step_number")))

            cursor.execute('''
                INSERT INTO recipe_ingredients (recipe_id, ingredient_id, amount, unit, prep_method, step_id)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                recipe_id,
                ingredient_id,
                ing.get("amount"),
                ing.get("unit"),
                ing.get("prep_method"),
                step_id
            ))


        # 6. Insert tags
        for tag in recipe_data.get("tags", []):
            raw_tag = tag.get("name")
            if not raw_tag or not raw_tag.strip():
                continue

            tag_name = raw_tag.strip().lower()

            cursor.execute('''
                INSERT INTO tags (name, category) VALUES (?, ?)
                ON CONFLICT(name) DO NOTHING
            ''', (tag_name, tag.get("category")))

            cursor.execute('SELECT tag_id FROM tags WHERE name = ?', (tag_name,))
            row = cursor.fetchone()
            if not row:
                continue
            tag_id = row[0]

            cursor.execute('''
                INSERT INTO recipe_tags (recipe_id, tag_id) VALUES (?, ?)
                ON CONFLICT(recipe_id, tag_id) DO NOTHING
            ''', (recipe_id, tag_id))

    conn.commit()
    conn.close()


def scrape_recipe(url: str) -> None:
    """Orginization function to complete entire scrape to normalization"""
    print(f"Scraping {url}", flush=True)
    start = time.time()
    clean_content = receive_and_clean(url)
    if not clean_content:
        print("  No content extracted, skipping", flush=True)
        return
    print(f"  Page fetched ({time.time() - start:.0f}s), {len(clean_content)} chars, sending to LLM...", flush=True)
    response = scrape_with_llm(clean_content)
    print(f"  LLM done ({time.time() - start:.0f}s), storing in DB...", flush=True)
    normalized_url = normalize_url(url)
    store_recipe_in_db(normalized_url, response)
    print(f"Completed {url} ({time.time() - start:.0f}s)", flush=True)

recipe_urls = [
    "https://www.bbcgoodfood.com/recipes/white-sourdough",
    "https://www.bbcgoodfood.com/recipes/focaccia",
    "https://www.bbcgoodfood.com/recipes/collection",
    "https://www.bbcgoodfood.com/recipes/chicken-pasta-bake",
    "https://www.bbcgoodfood.com/recipes/easy-chicken-curry",
    "https://www.bbcgoodfood.com/recipes/sausage-ragu",
    "https://www.bbcgoodfood.com/recipes/creamy-pesto-kale-pasta",
    "https://www.bbcgoodfood.com/recipes/fish-pie-mac-n-cheese",
    "https://www.bbcgoodfood.com/recipes/speedy-lentil-coconut-curry",
    "https://www.bbcgoodfood.com/recipes/fajita-style-pasta",
    "https://www.bbcgoodfood.com/recipes/creamy-garlic-pasta",
    "https://www.bbcgoodfood.com/recipes/meatball-black-bean-chilli",
    "https://www.bbcgoodfood.com/recipes/creamy-salmon-leek-potato-traybake",
    "https://www.bbcgoodfood.com/recipes/spicy-chickpea-stew",
    "https://www.bbcgoodfood.com/recipes/veggie-sausage-casserole",
    "https://www.bbcgoodfood.com/recipes/chicken-leek-brown-rice-stir-fry",
    "https://www.bbcgoodfood.com/recipes/gnocchi-cacio-e-pepe",
    "https://www.bbcgoodfood.com/recipes/roasted-carrot-whipped-feta-tart",
    "https://www.bbcgoodfood.com/recipes/bean-halloumi-stew",
    "https://www.bbcgoodfood.com/recipes/veggie-yaki-udon",
    "https://www.bbcgoodfood.com/recipes/piri-piri-chicken-smashed-sweet-potatoes-broccoli",
    "https://www.bbcgoodfood.com/recipes/roasted-cauliflower-chickpea-coconut-curry",
    "https://www.bbcgoodfood.com/recipes/paneer-korma",
    "https://www.bbcgoodfood.com/recipes/prawn-tikka-masala",
    "https://www.bbcgoodfood.com/recipes/cowboy-pie",
    "https://www.bbcgoodfood.com/recipes/creamy-chicken-stew",
    "https://www.bbcgoodfood.com/recipes/chicken-chorizo-jambalaya",
    "https://www.bbcgoodfood.com/recipes/spinach-sweet-potato-lentil-dhal",
    "https://www.bbcgoodfood.com/recipes/spicy-root-lentil-casserole",
    "https://www.bbcgoodfood.com/recipes/chinese-chicken-curry",
    "https://www.bbcgoodfood.com/recipes/chicken-jalfrezi",
    "https://www.bbcgoodfood.com/recipes/prawn-harissa-spaghetti",
    "https://www.bbcgoodfood.com/recipes/healthy-tikka-masala",
    "https://www.bbcgoodfood.com/recipes/chicken-korma",
    "https://www.bbcgoodfood.com/recipes/easy-risotto-bacon-peas",
    "https://www.bbcgoodfood.com/recipes/superhealthy-salmon-burgers",
    "https://www.bbcgoodfood.com/recipes/butter-bean-curry",
    "https://www.bbcgoodfood.com/recipes/pomegranate-chicken-almond-couscous",
    "https://www.bbcgoodfood.com/recipes/simple-fish-stew",
    "https://www.bbcgoodfood.com/recipes/pesto-sausage-traybake",
    "https://www.bbcgoodfood.com/recipes/healthy-chicken-burritos",
    "https://www.bbcgoodfood.com/recipes/curried-sate-noodles",
    "https://www.bbcgoodfood.com/recipes/healthy-gnocchi",
    "https://www.bbcgoodfood.com/recipes/healthy-chicken-pad-thai",
    "https://www.bbcgoodfood.com/recipes/tuna-caper-chilli-spaghetti",
    "https://www.bbcgoodfood.com/recipes/ginger-chicken-udon-noodles",
    "https://www.bbcgoodfood.com/recipes/one-pot-chicken-rice",
    "https://www.bbcgoodfood.com/recipes/curried-cod",
    "https://www.bbcgoodfood.com/recipes/one-pan-beef-stew-with-vegetable-mash",
    "https://www.bbcgoodfood.com/recipes/zesty-haddock-crushed-potatoes-peas",
    "https://www.bbcgoodfood.com/recipes/easy-vegetable-lasagne",
    "https://www.bbcgoodfood.com/recipes/satay-sweet-potato-curry",
    "https://www.bbcgoodfood.com/recipes/veggie-shepherds-pie-sweet-potato-mash",
    "https://www.bbcgoodfood.com/recipes/butternut-squash-sage-risotto",
    "https://www.bbcgoodfood.com/recipes/coconut-squash-dhansak",
    "https://www.bbcgoodfood.com/recipes/vegetarian-bolognese",
    "https://www.bbcgoodfood.com/recipes/vegetable-curry-crowd",
    "https://www.bbcgoodfood.com/recipes/indian-butternut-squash-curry",
    "https://www.bbcgoodfood.com/recipes/vegetable-pasta-bake",
    "https://www.bbcgoodfood.com/recipes/mexican-penne-avocado",
    "https://www.bbcgoodfood.com/recipes/tofu-stir-fry",
    "https://www.bbcgoodfood.com/recipes/veggie-burrito",
    "https://www.bbcgoodfood.com/recipes/creamy-broccoli-gnocchi",
    "https://www.bbcgoodfood.com/recipes/butternut-squash-casserole",
    "https://www.bbcgoodfood.com/recipes/butternut-squash-cherry-tomato-crumble",
    "https://www.bbcgoodfood.com/recipes/smoky-mushroom-chickpea-fajitas-with-charred-spring-onion-salsa",
    "https://www.bbcgoodfood.com/recipes/sticky-tempeh-stir-fry",
    "https://www.bbcgoodfood.com/recipes/simple-mushroom-curry",
    "https://www.bbcgoodfood.com/recipes/harissa-broccoli-flatbreads",
    "https://www.bbcgoodfood.com/recipes/sichuan-chicken"
]

for url in recipe_urls:
    try:
        scrape_recipe(url)
    except Exception as e:
        print(f"  FAILED {url}: {e}", flush=True)